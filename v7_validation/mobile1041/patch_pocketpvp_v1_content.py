#!/usr/bin/env python3
"""Install the minimal PocketPVP V1 licensed-slice server content.

This patch does not alter OTSP item artwork or item IDs. It adds only one
humanoid mechanics opponent using OTSP looktype 18 and verifies that the
frozen starter item IDs exist in the pinned OTSP item data.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "POCKETPVP_LICENSED_SLICE_V1"
RIVAL_FILE = "rpg rival.xml"

RIVAL_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<!-- POCKETPVP_LICENSED_SLICE_V1 -->
<monster name="RPG Rival" nameDescription="a rival combatant" race="blood" experience="0" speed="180" manacost="0">
    <health now="100" max="100" />
    <look type="18" />
    <targetchange interval="1000" chance="10" />
    <flags>
        <flag summonable="0" />
        <flag attackable="1" />
        <flag hostile="1" />
        <flag illusionable="0" />
        <flag convinceable="0" />
        <flag pushable="1" />
        <flag canpushitems="0" />
        <flag canpushcreatures="0" />
        <flag targetdistance="1" />
        <flag staticattack="90" />
        <flag runonhealth="0" />
    </flags>
    <attacks>
        <attack name="melee" interval="1200" min="-4" max="-12" />
    </attacks>
    <defenses armor="0" defense="0" />
    <loot>
    </loot>
</monster>
"""

REGISTER_LINE = f'\t<monster name="RPG Rival" file="{RIVAL_FILE}" />'


def patch(tfs: Path) -> None:
    items = tfs / "data" / "items" / "items.xml"
    monsters = tfs / "data" / "monster" / "monsters.xml"
    monster_dir = monsters.parent

    item_text = items.read_text(encoding="ISO-8859-1")
    if 'fromid="1677" toid="1799"' not in item_text:
        raise SystemExit("OTSP starter sword family 1677..1799 missing")
    if 'fromid="2099" toid="2102"' not in item_text:
        raise SystemExit("OTSP backpack family 2099..2102 missing")

    monster_dir.mkdir(parents=True, exist_ok=True)
    (monster_dir / RIVAL_FILE).write_text(RIVAL_XML, encoding="ISO-8859-1")

    text = monsters.read_text(encoding="utf-8")
    if REGISTER_LINE not in text:
        anchor = "</monsters>"
        if anchor not in text:
            raise SystemExit("OTSP monsters.xml closing tag missing")
        text = text.replace(anchor, REGISTER_LINE + "\n\n" + anchor, 1)
        monsters.write_text(text, encoding="utf-8")

    rival = (monster_dir / RIVAL_FILE).read_text(encoding="ISO-8859-1")
    registry = monsters.read_text(encoding="utf-8")
    assert MARKER in rival
    assert '<look type="18" />' in rival
    assert 'name="RPG Rival"' in registry
    print("PocketPVP licensed-slice server content: PASS")
    print("rival=RPG Rival looktype=18")
    print("starter_sword=1677 starter_backpack=2099")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("tfs", type=Path)
    a = p.parse_args()
    patch(a.tfs)


if __name__ == "__main__":
    main()
