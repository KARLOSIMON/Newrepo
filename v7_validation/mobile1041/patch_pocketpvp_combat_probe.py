#!/usr/bin/env python3
"""Add a V5 physical-test combat acknowledgement without changing combat rules.

The native Game::playerSetAttackedCreature path remains authoritative. For
GM Karlo only, emit a visible text message after Combat::canTargetCreature
accepts the target. This lets the Android physical test distinguish:
- touch/client failed to send attack;
- server rejected target;
- server accepted target but later combat execution failed.
"""
from pathlib import Path

PATH = Path("/src/tfs/src/game.cpp")
MARKER = "POCKETPVP_COMBAT_ACK_V1"

OLD = """	ReturnValue ret = Combat::canTargetCreature(player, attackCreature);
	if (ret != RET_NOERROR) {
		player->sendCancelMessage(ret);
		player->sendCancelTarget();
		player->setAttackedCreature(nullptr);
		return;
	}

	player->setAttackedCreature(attackCreature);
"""

NEW = """	ReturnValue ret = Combat::canTargetCreature(player, attackCreature);
	if (ret != RET_NOERROR) {
		player->sendCancelMessage(ret);
		player->sendCancelTarget();
		player->setAttackedCreature(nullptr);
		return;
	}

	// POCKETPVP_COMBAT_ACK_V1
	if (player->getName() == "GM Karlo") {
		player->sendTextMessage(MESSAGE_STATUS_DEFAULT,
			"PocketPVP V5 server accepted attack -> " + attackCreature->getName());
	}

	player->setAttackedCreature(attackCreature);
"""

text = PATH.read_text(encoding="utf-8")
if MARKER in text:
    print("PocketPVP V5 combat acknowledgement already present")
elif OLD not in text:
    raise SystemExit("playerSetAttackedCreature anchor changed; refusing unsafe patch")
else:
    PATH.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")

verify = PATH.read_text(encoding="utf-8")
assert MARKER in verify
assert "server accepted attack" in verify
print("PocketPVP V5 combat acknowledgement installed")
