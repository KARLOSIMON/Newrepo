# POCKETPVP V7 LICENSED VERTICAL SLICE — CLEAN 10.41
# Engine mechanics remain the pinned historical TFS 10.41 implementation.
# Client/server content namespace remains the pinned OTSP pairing.
# Production pixels are consumed from OTSP unchanged; this image does not run
# any PocketPVP sprite repaint/reskin step.
FROM debian:bookworm AS build

ARG TFS_SHA=73a22241a3dc231b52d9fe8c6a35d807b94109a0
ARG OTSP_SHA=ae88e1828671b349e729dd21177dde15ea41e123

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential ca-certificates cmake git python3 libboost-system-dev libgmp-dev \
    liblua5.2-dev default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY patch_portrait_aware_range.py /tmp/patch_portrait_aware_range.py
COPY build_pocketpvp_world.py /tmp/build_pocketpvp_world.py
COPY patch_pocketpvp_combat_probe.py /tmp/patch_pocketpvp_combat_probe.py
COPY patch_otsp_splash_ids.py /tmp/patch_otsp_splash_ids.py
COPY patch_pocketpvp_v1_content.py /tmp/patch_pocketpvp_v1_content.py

RUN git clone --filter=blob:none --no-checkout https://github.com/otland/forgottenserver.git tfs \
    && git -C tfs fetch --depth 1 origin "$TFS_SHA" \
    && git -C tfs checkout --detach "$TFS_SHA" \
    && test "$(git -C tfs rev-parse HEAD)" = "$TFS_SHA"

RUN git clone --filter=blob:none --no-checkout https://github.com/peonso/opentibia_sprite_pack.git otsp \
    && git -C otsp fetch --depth 1 origin "$OTSP_SHA" \
    && git -C otsp checkout --detach "$OTSP_SHA" \
    && test "$(git -C otsp rev-parse HEAD)" = "$OTSP_SHA"

# Railway adapter only: advertise the external game proxy port in the login list.
RUN sed -i '/#include "otpch.h"/a #include <cstdlib>' tfs/src/protocollogin.cpp \
    && sed -i 's#output->add<uint16_t>(g_config.getNumber(ConfigManager::GAME_PORT));#const char* publicGamePort = std::getenv("OT_PUBLIC_GAME_PORT"); output->add<uint16_t>(publicGamePort ? static_cast<uint16_t>(std::strtoul(publicGamePort, nullptr, 10)) : g_config.getNumber(ConfigManager::GAME_PORT));#' tfs/src/protocollogin.cpp

# Install the pinned OTSP data verbatim, then add only PocketPVP gameplay/content
# semantics around it. No item art, creature art, DAT or SPR bytes are repainted.
RUN cp otsp/server_files/items.otb tfs/data/items/items.otb \
    && cp otsp/server_files/items.xml tfs/data/items/items.xml \
    && python3 /tmp/patch_otsp_splash_ids.py tfs otsp/server_files/items.otb \
    && grep -F 'POCKETPVP_OTSP_SPLASH_IDS_V1' tfs/src/const.h \
    && rm -rf tfs/data/monster \
    && cp -a otsp/server_files/monster tfs/data/monster \
    && python3 /tmp/patch_pocketpvp_v1_content.py tfs \
    && grep -F 'POCKETPVP_LICENSED_SLICE_V1' 'tfs/data/monster/rpg rival.xml' \
    && grep -F '<look type="18" />' 'tfs/data/monster/rpg rival.xml' \
    && grep -F 'name="RPG Rival"' tfs/data/monster/monsters.xml \
    && grep -F 'fromid="1677" toid="1799"' tfs/data/items/items.xml \
    && grep -F 'fromid="2099" toid="2102"' tfs/data/items/items.xml \
    && python3 /tmp/build_pocketpvp_world.py --self-test \
    && python3 /tmp/build_pocketpvp_world.py tfs/data/world \
    && test -s tfs/data/world/pocketpvp.otbm \
    && test -s tfs/data/world/pocketpvp-spawn.xml \
    && test -s tfs/data/world/pocketpvp-house.xml \
    && grep -F '"world": "PocketPVP Licensed Slice V1"' tfs/data/world/pocketpvp-world-contract.json \
    && grep -F '"custom_sprite_generation": false' tfs/data/world/pocketpvp-world-contract.json \
    && grep -F '"starter_sword": 1677' tfs/data/world/pocketpvp-world-contract.json \
    && grep -F '"starter_backpack": 2099' tfs/data/world/pocketpvp-world-contract.json \
    && grep -F 'monster name="RPG Rival"' tfs/data/world/pocketpvp-spawn.xml \
    && ! grep -E 'Goblin|Mechanical Tactician' tfs/data/world/pocketpvp-spawn.xml

# The seeded test character owns its exact V1 equipment through entrypoint.sh.
# Keep first-login behavior inert so legacy starter assets do not leak into the slice.
RUN cat > tfs/data/creaturescripts/scripts/firstitems.lua <<'LUA'
function onLogin(cid)
    return true
end
LUA

# Transport/mobile-input compatibility only. No visual-art patch runs here.
RUN python3 /tmp/patch_portrait_aware_range.py \
    && python3 /tmp/patch_pocketpvp_combat_probe.py \
    && grep -F 'POCKETPVP_COMBAT_ACK_V1' tfs/src/game.cpp \
    && sed -i 's/boost::posix_time::seconds(Connection::read_timeout)/boost::posix_time::seconds(static_cast<long>(Connection::read_timeout))/g' tfs/src/connection.cpp \
    && sed -i 's/boost::posix_time::seconds(Connection::write_timeout)/boost::posix_time::seconds(static_cast<long>(Connection::write_timeout))/g' tfs/src/connection.cpp \
    && sed -i 's/-Wall -Werror/-Wall/' tfs/CMakeLists.txt \
    && mkdir -p tfs/build \
    && cd tfs/build \
    && cmake -DCMAKE_BUILD_TYPE=Release .. \
    && cmake --build . -j2

FROM debian:bookworm-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libboost-system1.74.0 libgmp10 liblua5.2-0 libmariadb3 mariadb-server mariadb-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY --from=build /src/tfs/build/tfs /usr/local/bin/tfs
COPY --from=build /src/tfs/data /srv/data
COPY --from=build /src/tfs/schema.sql /srv/schema.sql
COPY --from=build /src/tfs/config.lua /srv/config.lua.template
COPY entrypoint.sh /usr/local/bin/clean1041-entrypoint
RUN chmod +x /usr/local/bin/clean1041-entrypoint

EXPOSE 7171 7172
ENTRYPOINT ["/usr/local/bin/clean1041-entrypoint"]
