#!/bin/sh
set -eu

: "${OT_PUBLIC_IP:=${RAILWAY_TCP_PROXY_DOMAIN:-127.0.0.1}}"
: "${OT_PUBLIC_GAME_PORT:=${RAILWAY_TCP_PROXY_PORT:-7172}}"
: "${OT_SERVER_NAME:=PocketPVP}"
: "${MAX_PACKETS_PER_SECOND:=200}"

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=opentibia
MYSQL_PASSWORD=opentibia-mobile-1041
MYSQL_DATABASE=opentibia_mobile1041

mkdir -p /run/mysqld /var/lib/mysql
rm -rf /var/lib/mysql/*
chown -R mysql:mysql /run/mysqld /var/lib/mysql

mariadb-install-db \
  --auth-root-authentication-method=normal \
  --skip-test-db \
  --user=mysql \
  --datadir=/var/lib/mysql >/dev/null

mariadbd \
  --user=mysql \
  --datadir=/var/lib/mysql \
  --socket=/run/mysqld/mysqld.sock \
  --pid-file=/run/mysqld/mysqld.pid \
  --bind-address=127.0.0.1 \
  --port=3306 >/tmp/mobile1041-mariadb.log 2>&1 &
db_pid=$!

for i in $(seq 1 90); do
  if mariadb-admin --protocol=socket --socket=/run/mysqld/mysqld.sock ping --silent >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$db_pid" >/dev/null 2>&1; then
    echo "[POCKETPVP-DB] MariaDB exited during startup"
    cat /tmp/mobile1041-mariadb.log || true
    exit 1
  fi
  sleep 1
done

mariadb --protocol=socket --socket=/run/mysqld/mysqld.sock <<'SQL'
CREATE DATABASE IF NOT EXISTS opentibia_mobile1041;
CREATE USER IF NOT EXISTS 'opentibia'@'127.0.0.1' IDENTIFIED BY 'opentibia-mobile-1041';
ALTER USER 'opentibia'@'127.0.0.1' IDENTIFIED BY 'opentibia-mobile-1041';
GRANT ALL PRIVILEGES ON opentibia_mobile1041.* TO 'opentibia'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL

cp /srv/config.lua.template /srv/config.lua

sed -i "s#^ip = .*#ip = \"$OT_PUBLIC_IP\"#" /srv/config.lua
sed -i "s#^serverName = .*#serverName = \"$OT_SERVER_NAME\"#" /srv/config.lua
sed -i 's#^mapName = .*#mapName = "pocketpvp"#' /srv/config.lua
sed -i "s#^mysqlHost = .*#mysqlHost = \"$MYSQL_HOST\"#" /srv/config.lua
sed -i "s#^mysqlUser = .*#mysqlUser = \"$MYSQL_USER\"#" /srv/config.lua
sed -i "s#^mysqlPass = .*#mysqlPass = \"$MYSQL_PASSWORD\"#" /srv/config.lua
sed -i "s#^mysqlDatabase = .*#mysqlDatabase = \"$MYSQL_DATABASE\"#" /srv/config.lua
sed -i "s#^mysqlPort = .*#mysqlPort = $MYSQL_PORT#" /srv/config.lua
sed -i 's#^freePremium = .*#freePremium = "yes"#' /srv/config.lua
sed -i 's#^protectionLevel = .*#protectionLevel = 1#' /srv/config.lua
sed -i 's#^maxPlayers = .*#maxPlayers = 100#' /srv/config.lua
sed -i "s#^maxPacketsPerSecond = .*#maxPacketsPerSecond = $MAX_PACKETS_PER_SECOND#" /srv/config.lua

TABLES=$(mariadb -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" -Nse \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$MYSQL_DATABASE';" 2>/dev/null || echo 0)
if [ "$TABLES" = "0" ]; then
  mariadb -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" < /srv/schema.sql
fi

mariadb -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" <<'SQL'
INSERT INTO accounts (name,password,type,premdays,lastday,email,creation)
VALUES ('a','86f7e437faa5a7fce15d1ddcb9eaeaea377667b8',1,3650,0,'',0)
ON DUPLICATE KEY UPDATE password=VALUES(password);

SET @clean_account_id = (SELECT id FROM accounts WHERE name='a' LIMIT 1);

INSERT INTO players (
  id,name,group_id,account_id,level,vocation,health,healthmax,experience,
  lookbody,lookfeet,lookhead,looklegs,looktype,lookaddons,
  maglevel,mana,manamax,manaspent,soul,town_id,posx,posy,posz,
  conditions,cap,sex
) VALUES (
  9001,'GM Karlo',1,@clean_account_id,20,1,250,250,98800,
  0,0,0,0,17,0,
  5,100,100,0,100,1,33008,33018,7,
  '',1000,1
)
ON DUPLICATE KEY UPDATE
  account_id=@clean_account_id, group_id=1, looktype=17, town_id=1,
  posx=33008,posy=33018,posz=7,
  health=250,healthmax=250,mana=100,manamax=100;

UPDATE players
SET skill_fist=30, skill_sword=80, skill_shielding=40
WHERE id=9001;

-- V1 frozen licensed equipment: OTSP backpack 2099 and sword 1677 only.
DELETE FROM player_items
WHERE player_id=9001;

INSERT INTO player_items (player_id,pid,sid,itemtype,count,attributes)
VALUES
  (9001,3,100,2099,1,''),
  (9001,6,101,1677,1,'');
SQL

verification=$(mariadb -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -Nse \
  "SELECT CONCAT(name,'|',group_id,'|',looktype,'|',town_id,'|',posx,',',posy,',',posz) FROM players WHERE id=9001 LIMIT 1;")
if [ "$verification" != "GM Karlo|1|17|1|33008,33018,7" ]; then
  echo "[POCKETPVP] GM Karlo seed verification failed: $verification" >&2
  exit 1
fi

backpack_verification=$(mariadb -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -Nse \
  "SELECT CONCAT(pid,'|',itemtype,'|',count) FROM player_items WHERE player_id=9001 AND itemtype=2099 LIMIT 1;")
if [ "$backpack_verification" != "3|2099|1" ]; then
  echo "[POCKETPVP] licensed backpack seed verification failed: $backpack_verification" >&2
  exit 1
fi

combat_verification=$(mariadb -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -Nse \
  "SELECT CONCAT(pi.pid,'|',pi.itemtype,'|',p.skill_sword) FROM player_items pi JOIN players p ON p.id=pi.player_id WHERE pi.player_id=9001 AND pi.itemtype=1677 LIMIT 1;")
if [ "$combat_verification" != "6|1677|80" ]; then
  echo "[POCKETPVP] licensed sword seed verification failed: $combat_verification" >&2
  exit 1
fi

export OT_PUBLIC_GAME_PORT
echo "[POCKETPVP] isolated local MariaDB ready"
echo "[POCKETPVP] V1 player seed verified: $verification"
echo "[POCKETPVP] V1 backpack seed verified: $backpack_verification"
echo "[POCKETPVP] V1 sword seed verified: $combat_verification"
echo "[POCKETPVP] licensed OTSP vertical slice starting"
echo "[POCKETPVP] advertised world route: $OT_PUBLIC_IP:$OT_PUBLIC_GAME_PORT"
exec /usr/local/bin/tfs
