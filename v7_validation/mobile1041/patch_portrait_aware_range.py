#!/usr/bin/env python3
"""Patch historical TFS 10.41 map streaming to an OTClient portrait aware range.

Presentation transport only:
- server gameplay/map authority is unchanged;
- OTClient already supports GameServerChangeMapAwareRange (0x33);
- 15x35 gives a tall-phone field while preserving native tile geometry.
"""
from pathlib import Path

path = Path("/src/tfs/src/protocolgame.cpp")
text = path.read_text(encoding="utf-8")

replacements = {
    "if ((x >= myPos.getX() - 8 + offsetz) && (x <= myPos.getX() + 9 + offsetz) &&\n\t        (y >= myPos.getY() - 6 + offsetz) && (y <= myPos.getY() + 7 + offsetz)) {":
    "if ((x >= myPos.getX() - 7 + offsetz) && (x <= myPos.getX() + 7 + offsetz) &&\n\t        (y >= myPos.getY() - 17 + offsetz) && (y <= myPos.getY() + 17 + offsetz)) {",

    "GetMapDescription(pos.x - 8, pos.y - 6, pos.z, 18, 14, msg);":
    "GetMapDescription(pos.x - 7, pos.y - 17, pos.z, 15, 35, msg);",

    "GetMapDescription(oldPos.x - 8, newPos.y - 6, newPos.z, 18, 1, msg);":
    "GetMapDescription(oldPos.x - 7, newPos.y - 17, newPos.z, 15, 1, msg);",

    "GetMapDescription(oldPos.x - 8, newPos.y + 7, newPos.z, 18, 1, msg);":
    "GetMapDescription(oldPos.x - 7, newPos.y + 17, newPos.z, 15, 1, msg);",

    "GetMapDescription(newPos.x + 9, newPos.y - 6, newPos.z, 1, 14, msg);":
    "GetMapDescription(newPos.x + 7, newPos.y - 17, newPos.z, 1, 35, msg);",

    "GetMapDescription(newPos.x - 8, newPos.y - 6, newPos.z, 1, 14, msg);":
    "GetMapDescription(newPos.x - 7, newPos.y - 17, newPos.z, 1, 35, msg);",

    "oldPos.x - 8, oldPos.y - 6, 5, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, 5, 15, 35",
    "oldPos.x - 8, oldPos.y - 6, 4, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, 4, 15, 35",
    "oldPos.x - 8, oldPos.y - 6, 3, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, 3, 15, 35",
    "oldPos.x - 8, oldPos.y - 6, 2, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, 2, 15, 35",
    "oldPos.x - 8, oldPos.y - 6, 1, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, 1, 15, 35",
    "oldPos.x - 8, oldPos.y - 6, 0, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, 0, 15, 35",

    "oldPos.x - 8, oldPos.y - 6, oldPos.getZ() - 3, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, oldPos.getZ() - 3, 15, 35",

    "GetMapDescription(oldPos.x - 8, oldPos.y - 5, newPos.z, 1, 14, msg);":
    "GetMapDescription(oldPos.x - 7, oldPos.y - 16, newPos.z, 1, 35, msg);",

    "GetMapDescription(oldPos.x - 8, oldPos.y - 6, newPos.z, 18, 1, msg);":
    "GetMapDescription(oldPos.x - 7, oldPos.y - 17, newPos.z, 15, 1, msg);",

    "oldPos.x - 8, oldPos.y - 6, newPos.z, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, newPos.z, 15, 35",
    "oldPos.x - 8, oldPos.y - 6, newPos.z + 1, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, newPos.z + 1, 15, 35",
    "oldPos.x - 8, oldPos.y - 6, newPos.z + 2, 18, 14":
    "oldPos.x - 7, oldPos.y - 17, newPos.z + 2, 15, 35",

    "GetMapDescription(oldPos.x + 9, oldPos.y - 7, newPos.z, 1, 14, msg);":
    "GetMapDescription(oldPos.x + 7, oldPos.y - 18, newPos.z, 1, 35, msg);",

    "GetMapDescription(oldPos.x - 8, oldPos.y + 7, newPos.z, 18, 1, msg);":
    "GetMapDescription(oldPos.x - 7, oldPos.y + 17, newPos.z, 15, 1, msg);",
}

for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"portrait aware-range anchor missing: {old}")
    text = text.replace(old, new)

# Tell modern OTClient the server-side aware dimensions before the first map.
anchor = """\tsendPendingStateEntered();\n\tsendEnterWorld();\n\tsendMapDescription(pos);"""
replacement = """\tsendPendingStateEntered();\n\tsendEnterWorld();\n\n\t// OTClient custom opcode 0x33: map aware range (width, height).\n\t// Presentation transport only; world simulation remains native TFS.\n\t{\n\t\tNetworkMessage aware;\n\t\taware.AddByte(0x33);\n\t\taware.AddByte(15);\n\t\taware.AddByte(35);\n\t\twriteToOutputBuffer(aware);\n\t}\n\n\tsendMapDescription(pos);"""
if anchor not in text:
    raise SystemExit("login aware-range insertion anchor missing")
text = text.replace(anchor, replacement, 1)

# Sanity: desktop dimensions should no longer drive the player map stream.
for forbidden in (
    "GetMapDescription(pos.x - 8, pos.y - 6, pos.z, 18, 14, msg);",
    "newPos.y - 6, newPos.z, 18, 1",
    "newPos.z, 1, 14",
):
    if forbidden in text:
        raise SystemExit(f"desktop map-stream fragment remains: {forbidden}")

path.write_text(text, encoding="utf-8")
print("CLEAN1041 portrait aware range 15x35: patched")
