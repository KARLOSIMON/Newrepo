#!/usr/bin/env python3
"""Build the minimal PocketPVP licensed vertical-slice world.

The map uses only the frozen V1 OTSP visual manifest. No generated/reskinned
sprites are required. Layout and topology are PocketPVP-authored; the rendered
pixels come directly from the pinned CC-BY-4.0 OpenTibia Sprite Pack.

Scope:
- grass ground family 101..105;
- accepted 5x4 rectangular building grammar using OTSP roof/wall/facade IDs;
- player/rival visual contract is handled by server/client looktypes 17/18;
- starter sword 1677 and backpack 2099 are present as real world items;
- one humanoid RPG Rival spawn;
- no creature-art dependency, no water/torch/shrine/custom-effect dependency.
"""
from __future__ import annotations

import argparse
import json
import struct
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

IDENT = b"OTBM"
NS = 0xFE
NE = 0xFF
ESC = 0xFD

ROOT = 1
MAP = 2
AREA = 4
TILE = 5
TOWNS = 12
TOWN = 13

A_DESC = 1
A_FLAGS = 3
A_ITEM = 9
A_SPAWN = 11
A_HOUSE = 13

PZ = 1

BASE_X = 33000
BASE_Y = 33000
GROUND_Z = 7
ROOF_Z = 6
W = 40
H = 30
TEMPLE = (33008, 33018, GROUND_Z)

GRASS = (101, 102, 103, 104, 105)

ROOF_NORTH = 189
ROOF_FILL = 190
ROOF_SOUTH_EDGE = 508

BASE_WALL = {
    "vertical": 651,
    "horizontal": 652,
    "pole": 653,
    "corner": 657,
}
FACADE = {
    "east_wall": 661,
    "east_window": 663,
    "south_wall": 662,
    "south_window": 664,
    "south_door": 668,
    "se_corner": 660,
}
HALF = {
    0: "pole", 1: "vertical", 2: "horizontal", 3: "corner",
    4: "pole", 5: "vertical", 6: "horizontal", 7: "corner",
    8: "pole", 9: "vertical", 10: "horizontal", 11: "corner",
    12: "pole", 13: "vertical", 14: "horizontal", 15: "corner",
}

STARTER_SWORD = 1677
STARTER_BACKPACK = 2099

BUILDING_ORIGIN = (6, 6)
BUILDING_W = 5
BUILDING_H = 4

SPAWNS = (
    ("RPG Rival", 33024, 33016, GROUND_Z, 1, 10),
)

ALLOWED_ITEM_IDS = {
    *GRASS,
    ROOF_NORTH, ROOF_FILL, ROOF_SOUTH_EDGE,
    *BASE_WALL.values(), *FACADE.values(),
    STARTER_SWORD, STARTER_BACKPACK,
}


def u8(v: int) -> bytes:
    return struct.pack("<B", v)


def u16(v: int) -> bytes:
    return struct.pack("<H", v)


def u32(v: int) -> bytes:
    return struct.pack("<I", v)


def s(v: str) -> bytes:
    data = v.encode("utf-8")
    return u16(len(data)) + data


def esc(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b in (NS, NE, ESC):
            out.append(ESC)
        out.append(b)
    return bytes(out)


def node(t: int, props: bytes = b"", children=()) -> bytes:
    return bytes((NS, t)) + esc(props) + b"".join(children) + bytes((NE,))


def hash2(x: int, y: int, seed: int) -> int:
    v = (x * 0x1F123BB5) ^ (y * 0x5F356495) ^ (seed * 0x27D4EB2D)
    v = (v ^ (v >> 15)) * 0x85EBCA6B
    v = (v ^ (v >> 13)) * 0xC2B2AE35
    return (v ^ (v >> 16)) & 0xFFFFFFFF


def weighted(ids, weights, x: int, y: int, seed: int) -> int:
    total = sum(weights)
    n = hash2(x, y, seed) % total
    acc = 0
    for iid, weight in zip(ids, weights):
        acc += weight
        if n < acc:
            return iid
    return ids[-1]


def grass_id(x: int, y: int) -> int:
    return weighted(GRASS, (84, 5, 4, 4, 3), x, y, 101)


def building_boundary() -> set[tuple[int, int]]:
    ox, oy = BUILDING_ORIGIN
    pts: set[tuple[int, int]] = set()
    for x in range(BUILDING_W):
        pts.add((ox + x, oy))
        pts.add((ox + x, oy + BUILDING_H - 1))
    for y in range(BUILDING_H):
        pts.add((ox, oy + y))
        pts.add((ox + BUILDING_W - 1, oy + y))
    return pts


def cardinal(points: set[tuple[int, int]], x: int, y: int) -> int:
    mask = 0
    if (x, y - 1) in points:
        mask |= 1
    if (x - 1, y) in points:
        mask |= 2
    if (x + 1, y) in points:
        mask |= 4
    if (x, y + 1) in points:
        mask |= 8
    return mask


def lower_objects() -> dict[tuple[int, int], list[int]]:
    out: dict[tuple[int, int], list[int]] = {}
    topo = building_boundary()
    ox, oy = BUILDING_ORIGIN
    east_windows = {(ox + BUILDING_W - 1, oy + 1), (ox + BUILDING_W - 1, oy + 2)}
    south_y = oy + BUILDING_H - 1
    south_windows = {(ox, south_y), (ox + 3, south_y)}
    south_door = (ox + 2, south_y)
    se = (ox + BUILDING_W - 1, south_y)

    for pos in sorted(topo, key=lambda p: (p[1], p[0])):
        role = HALF[cardinal(topo, *pos)]
        iid = BASE_WALL[role]

        if pos[0] == ox + BUILDING_W - 1 and pos != se:
            iid = FACADE["east_window"] if pos in east_windows else FACADE["east_wall"]

        if pos[1] == south_y:
            if pos in south_windows:
                iid = FACADE["south_window"]
            elif pos == south_door:
                iid = FACADE["south_door"]
            elif pos == se:
                iid = FACADE["se_corner"]
            else:
                iid = FACADE["south_wall"]

        out.setdefault(pos, []).append(iid)

    out.setdefault((8, 18), []).append(STARTER_BACKPACK)
    out.setdefault((9, 18), []).append(STARTER_SWORD)
    return out


def roof_objects() -> dict[tuple[int, int], list[int]]:
    out: dict[tuple[int, int], list[int]] = {}
    ox, oy = BUILDING_ORIGIN
    for y in range(BUILDING_H):
        for x in range(BUILDING_W):
            pos = (ox + x, oy + y)
            if y == 0:
                out[pos] = [ROOF_NORTH]
            elif y == BUILDING_H - 1:
                out[pos] = [ROOF_FILL, ROOF_SOUTH_EDGE]
            else:
                out[pos] = [ROOF_FILL]
    return out


def protection_zone(x: int, y: int) -> bool:
    return 2 <= x <= 16 and 13 <= y <= 24


def make_area(z: int, stacks: dict[tuple[int, int], tuple[int, ...]]) -> bytes:
    children = []
    for (x, y), stack in sorted(stacks.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        props = bytearray((x, y))
        if z == GROUND_Z and protection_zone(x, y):
            props += u8(A_FLAGS) + u32(PZ)
        for iid in stack:
            if iid not in ALLOWED_ITEM_IDS:
                raise RuntimeError(f"item outside frozen V1 manifest: {iid}")
            props += u8(A_ITEM) + u16(iid)
        children.append(node(TILE, bytes(props)))
    return node(AREA, u16(BASE_X) + u16(BASE_Y) + u8(z), children)


def build() -> tuple[bytes, dict]:
    lower = lower_objects()
    ground_stacks: dict[tuple[int, int], tuple[int, ...]] = {}
    for y in range(H):
        for x in range(W):
            stack = [grass_id(x, y)]
            stack.extend(lower.get((x, y), ()))
            ground_stacks[(x, y)] = tuple(stack)

    roof_stacks = {pos: tuple(stack) for pos, stack in roof_objects().items()}

    ground_area = make_area(GROUND_Z, ground_stacks)
    roof_area = make_area(ROOF_Z, roof_stacks)

    towns = node(
        TOWNS,
        b"",
        (
            node(
                TOWN,
                u32(1)
                + s("PocketPVP Licensed Slice")
                + u16(TEMPLE[0])
                + u16(TEMPLE[1])
                + u8(TEMPLE[2]),
            ),
        ),
    )

    props = (
        u8(A_DESC) + s("PocketPVP licensed vertical slice V1")
        + u8(A_SPAWN) + s("pocketpvp-spawn.xml")
        + u8(A_HOUSE) + s("pocketpvp-house.xml")
    )
    mapnode = node(MAP, props, (ground_area, roof_area, towns))
    root = struct.pack("<IHHII", 2, 65535, 65535, 3, 55)
    payload = IDENT + node(ROOT, root, (mapnode,))

    used = sorted({iid for stack in ground_stacks.values() for iid in stack}
                  | {iid for stack in roof_stacks.values() for iid in stack})

    contract = {
        "schema_version": 4,
        "world": "PocketPVP Licensed Slice V1",
        "map": {
            "width": W,
            "height": H,
            "base_x": BASE_X,
            "base_y": BASE_Y,
            "ground_z": GROUND_Z,
            "roof_z": ROOF_Z,
            "temple": list(TEMPLE),
        },
        "copyright": "pocketpvp_original_layout_with_licensed_otsp_pixels",
        "licensed_visual_manifest": {
            "grass": list(GRASS),
            "roof": [ROOF_NORTH, ROOF_FILL, ROOF_SOUTH_EDGE],
            "wall": sorted(BASE_WALL.values()),
            "facade": sorted(FACADE.values()),
            "starter_sword": STARTER_SWORD,
            "starter_backpack": STARTER_BACKPACK,
            "used_item_ids": used,
        },
        "building": {
            "origin": list(BUILDING_ORIGIN),
            "width": BUILDING_W,
            "height": BUILDING_H,
            "roof_alignment": {"x_delta": 0, "y_delta": 0, "z_delta": -1},
            "rectangular_grammar_v1": True,
        },
        "spawns": [
            {"name": n, "x": x, "y": y, "z": z, "radius": r, "seconds": sec}
            for n, x, y, z, r, sec in SPAWNS
        ],
        "mechanics_contract": {
            "server_authoritative": True,
            "native_collision": True,
            "native_pathing": True,
            "native_combat": True,
            "custom_movement": False,
            "custom_sprite_generation": False,
        },
    }
    return payload, contract


def spawn_xml() -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<spawns>"]
    for name, x, y, z, radius, sec in SPAWNS:
        lines += [
            f'  <spawn centerx="{x}" centery="{y}" centerz="{z}" radius="{radius}">',
            f'    <monster name="{xml_escape(name)}" x="0" y="0" z="{z}" spawntime="{sec}" />',
            "  </spawn>",
        ]
    lines.append("</spawns>")
    return "\n".join(lines) + "\n"


def write(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    payload, contract = build()
    (out / "pocketpvp.otbm").write_bytes(payload)
    (out / "pocketpvp-spawn.xml").write_text(spawn_xml(), encoding="utf-8")
    (out / "pocketpvp-house.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<houses/>\n',
        encoding="utf-8",
    )
    (out / "pocketpvp-world-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(contract, indent=2, sort_keys=True))
    return contract


def selftest() -> None:
    payload, contract = build()
    assert payload.startswith(b"OTBM" + bytes((NS, ROOT)))
    assert payload.count(bytes((NS, TILE))) >= W * H + BUILDING_W * BUILDING_H
    assert contract["map"]["temple"] == list(TEMPLE)
    assert contract["building"]["roof_alignment"]["z_delta"] == -1
    assert contract["spawns"][0]["name"] == "RPG Rival"
    assert set(contract["licensed_visual_manifest"]["used_item_ids"]) <= ALLOWED_ITEM_IDS
    assert STARTER_SWORD in contract["licensed_visual_manifest"]["used_item_ids"]
    assert STARTER_BACKPACK in contract["licensed_visual_manifest"]["used_item_ids"]
    with tempfile.TemporaryDirectory(prefix="pocketpvp-licensed-v1-") as d:
        result = write(Path(d))
        assert result["world"] == "PocketPVP Licensed Slice V1"
    print("PocketPVP licensed vertical-slice world self-test: PASS")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("output", nargs="?", type=Path)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        selftest()
    if args.output:
        write(args.output)
    if not args.self_test and not args.output:
        selftest()


if __name__ == "__main__":
    main()
