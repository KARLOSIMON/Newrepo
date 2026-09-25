#!/usr/bin/env python3
"""Build the RPGGAME DAT/SPR structural catalog from the pinned OTSP baseline.

This pass records render structure and sprite ownership only. It does not decode,
copy, or emit sprite pixels. The resulting catalog is designed to answer two
questions before any reskin:

1. What is the exact render envelope / pattern / animation topology of each thing?
2. Which sprite payloads are exclusive versus shared by multiple things?

The non-sprite binary prefix of each DAT thing record is fingerprinted so future
visual-only tooling can prove it changed only sprite references/pixels and did not
silently mutate attributes or topology.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from otsp_humanoid_generator import _Reader, _skip_attrs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OTSP = ROOT / ".work" / "otsp-source"
DEFAULT_OUT = ROOT / ".work" / "dat_structure_catalog"
PINNED_OTSP_COMMIT = "ae88e1828671b349e729dd21177dde15ea41e123"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def parse_spr_header(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    if len(data) < 8:
        raise RuntimeError("SPR file is truncated")
    return {
        "signature": int.from_bytes(data[0:4], "little"),
        "sprite_count": int.from_bytes(data[4:8], "little"),
        "bytes": len(data),
    }


def parse_thing(reader: _Reader, raw: bytes, category: str, thing_id: int) -> dict[str, Any]:
    record_start = reader.pos

    _skip_attrs(reader)
    attrs_end = reader.pos

    width = reader.u8()
    height = reader.u8()
    real_size = reader.u8() if width > 1 or height > 1 else 32
    layers = reader.u8()
    pattern_x = reader.u8()
    pattern_y = reader.u8()
    pattern_z = reader.u8()
    phases = reader.u8()

    sprite_count = width * height * layers * pattern_x * pattern_y * pattern_z * phases
    sprite_offset = reader.pos
    sprites = [reader.u32() for _ in range(sprite_count)]
    record_end = reader.pos

    shape = {
        "width_blocks": width,
        "height_blocks": height,
        "real_size": real_size,
        "layers": layers,
        "pattern_x": pattern_x,
        "pattern_y": pattern_y,
        "pattern_z": pattern_z,
        "animation_phases": phases,
        "sprite_ref_slots": sprite_count,
    }
    nonzero = [int(sid) for sid in sprites if int(sid) != 0]

    return {
        "category": category,
        "id": thing_id,
        "owner_ref": f"{category}:{thing_id}",
        **shape,
        "ordered_sprite_refs": [int(sid) for sid in sprites],
        "nonzero_sprite_ref_count": len(nonzero),
        "unique_sprite_ids": sorted(set(nonzero)),
        "duplicate_ref_slots": len(nonzero) - len(set(nonzero)),
        "record_offsets": {
            "start": record_start,
            "attrs_end": attrs_end,
            "sprite_refs_start": sprite_offset,
            "end": record_end,
        },
        "attributes_fingerprint_sha256": sha256_bytes(raw[record_start:attrs_end]),
        "shape_fingerprint_sha256": canonical_sha256(shape),
        "non_sprite_prefix_fingerprint_sha256": sha256_bytes(raw[record_start:sprite_offset]),
        "record_fingerprint_sha256": sha256_bytes(raw[record_start:record_end]),
    }


def parse_dat(path: Path) -> tuple[dict[str, int], list[dict[str, Any]]]:
    raw = path.read_bytes()
    reader = _Reader(raw)
    header = {
        "signature": reader.u32(),
        "item_max": reader.u16(),
        "creature_max": reader.u16(),
        "effect_max": reader.u16(),
        "missile_max": reader.u16(),
        "bytes": len(raw),
    }

    things: list[dict[str, Any]] = []
    for thing_id in range(100, header["item_max"] + 1):
        things.append(parse_thing(reader, raw, "item", thing_id))
    for thing_id in range(1, header["creature_max"] + 1):
        things.append(parse_thing(reader, raw, "creature", thing_id))
    for thing_id in range(1, header["effect_max"] + 1):
        things.append(parse_thing(reader, raw, "effect", thing_id))
    for thing_id in range(1, header["missile_max"] + 1):
        things.append(parse_thing(reader, raw, "missile", thing_id))

    if reader.pos != len(raw):
        raise RuntimeError(f"DAT parse incomplete: {reader.pos}/{len(raw)}")

    return header, things


def attach_ownership(things: list[dict[str, Any]]) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    reverse: defaultdict[int, set[str]] = defaultdict(set)
    slot_counts: Counter[int] = Counter()

    for thing in things:
        owner = thing["owner_ref"]
        for sid in thing["ordered_sprite_refs"]:
            sid = int(sid)
            if sid <= 0:
                continue
            reverse[sid].add(owner)
            slot_counts[sid] += 1

    sprite_records: dict[int, dict[str, Any]] = {}
    for sid, owners in sorted(reverse.items()):
        ordered = sorted(owners)
        cats = sorted({owner.split(":", 1)[0] for owner in ordered})
        sprite_records[sid] = {
            "sprite_id": sid,
            "owners": ordered,
            "owner_count": len(ordered),
            "categories": cats,
            "cross_category_shared": len(cats) > 1,
            "reference_slot_count": int(slot_counts[sid]),
            "shared": len(ordered) > 1,
        }

    owner_to_shared: defaultdict[str, set[int]] = defaultdict(set)
    owner_to_other_refs: defaultdict[str, set[str]] = defaultdict(set)
    for sid, sprite in sprite_records.items():
        if not sprite["shared"]:
            continue
        owners = sprite["owners"]
        for owner in owners:
            owner_to_shared[owner].add(sid)
            owner_to_other_refs[owner].update(o for o in owners if o != owner)

    strategy_counts: Counter[str] = Counter()
    for thing in things:
        owner = thing["owner_ref"]
        shared_ids = sorted(owner_to_shared.get(owner, set()))
        other_refs = sorted(owner_to_other_refs.get(owner, set()))
        thing["shared_sprite_ids"] = shared_ids
        thing["shared_visual_refs"] = other_refs
        thing["shared_sprite_count"] = len(shared_ids)
        thing["shared_other_thing_count"] = len(other_refs)

        if thing["category"] in {"effect", "missile"}:
            strategy = "PROTECTED_DO_NOT_REPAINT"
            safe = False
        elif not thing["unique_sprite_ids"]:
            strategy = "NO_SPRITE_PAYLOAD"
            safe = False
        elif shared_ids:
            strategy = "CLONE_SHARED_SPRITES_THEN_REDIRECT_THIS_THING"
            safe = True
        else:
            strategy = "DIRECT_REPAINT_ISOLATED_SPRITES"
            safe = True
        thing["repaint_strategy"] = strategy
        thing["safe_to_repaint_with_strategy"] = safe
        strategy_counts[strategy] += 1

    return sprite_records, dict(sorted(strategy_counts.items()))


def validate(
    header: dict[str, int],
    spr_header: dict[str, int],
    things: list[dict[str, Any]],
    sprites: dict[int, dict[str, Any]],
) -> None:
    by_ref = {thing["owner_ref"]: thing for thing in things}

    expected_counts = {
        "item": header["item_max"] - 99,
        "creature": header["creature_max"],
        "effect": header["effect_max"],
        "missile": header["missile_max"],
    }
    observed = Counter(thing["category"] for thing in things)
    if dict(observed) != expected_counts:
        raise RuntimeError(f"thing counts disagree: observed={dict(observed)} expected={expected_counts}")

    for thing in things:
        formula = (
            thing["width_blocks"] * thing["height_blocks"] * thing["layers"]
            * thing["pattern_x"] * thing["pattern_y"] * thing["pattern_z"]
            * thing["animation_phases"]
        )
        if formula != len(thing["ordered_sprite_refs"]):
            raise RuntimeError(f"sprite slot formula mismatch for {thing['owner_ref']}")
        if thing["unique_sprite_ids"] and max(thing["unique_sprite_ids"]) > spr_header["sprite_count"]:
            raise RuntimeError(f"SPR id out of bounds for {thing['owner_ref']}")

    # Stable baseline probes from the pinned OTSP corpus.
    player = by_ref.get("creature:17")
    if not player:
        raise RuntimeError("missing OTSP humanoid looktype 17")
    player_shape = (
        player["width_blocks"], player["height_blocks"], player["layers"],
        player["pattern_x"], player["pattern_y"], player["pattern_z"],
        player["animation_phases"],
    )
    if player_shape != (2, 2, 2, 4, 1, 1, 3):
        raise RuntimeError(f"OTSP humanoid topology changed: {player_shape}")

    item126 = by_ref.get("item:126")
    item990 = by_ref.get("item:990")
    if not item126 or not item990:
        raise RuntimeError("known shared-sprite probe items are missing")
    if not (set(item126["unique_sprite_ids"]) & set(item990["unique_sprite_ids"])):
        raise RuntimeError("known item 126/990 shared-sprite hazard was not detected")

    if not any(sprite["shared"] for sprite in sprites.values()):
        raise RuntimeError("reverse ownership graph detected no shared sprites")


def build_catalog(otsp_root: Path) -> dict[str, Any]:
    dat_path = otsp_root / "client_files" / "otsp.dat"
    spr_path = otsp_root / "client_files" / "otsp.spr"
    if not dat_path.is_file() or not spr_path.is_file():
        raise SystemExit(f"missing pinned OTSP DAT/SPR under {otsp_root / 'client_files'}")

    header, things = parse_dat(dat_path)
    spr_header = parse_spr_header(spr_path)
    sprite_records, strategy_counts = attach_ownership(things)
    validate(header, spr_header, things, sprite_records)

    category_counts = Counter(thing["category"] for thing in things)
    shape_counts = Counter(
        (
            thing["category"],
            thing["width_blocks"], thing["height_blocks"], thing["layers"],
            thing["pattern_x"], thing["pattern_y"], thing["pattern_z"],
            thing["animation_phases"],
        )
        for thing in things
    )

    shared_ids = [sid for sid, rec in sprite_records.items() if rec["shared"]]
    cross_category = [sid for sid, rec in sprite_records.items() if rec["cross_category_shared"]]
    referenced = set(sprite_records)
    all_sprites = set(range(1, spr_header["sprite_count"] + 1))

    return {
        "schema_version": 1,
        "source": {
            "repository": "peonso/opentibia_sprite_pack",
            "pinned_commit": PINNED_OTSP_COMMIT,
            "dat_path": "client_files/otsp.dat",
            "spr_path": "client_files/otsp.spr",
        },
        "contract": {
            "structural_inventory_only": True,
            "sprite_pixels_included": False,
            "mechanics_modified": False,
            "dat_attributes_modified": False,
            "effects_missiles_protected": True,
            "safe_visual_edit_rule": (
                "Preserve the non-sprite DAT prefix exactly. Repaint isolated sprite payloads directly; "
                "for shared payloads, clone and redirect only the intended thing's sprite references."
            ),
        },
        "dat_header": header,
        "spr_header": spr_header,
        "metrics": {
            "thing_count": len(things),
            "category_counts": dict(sorted(category_counts.items())),
            "referenced_unique_sprite_ids": len(referenced),
            "unreferenced_sprite_ids": len(all_sprites - referenced),
            "shared_sprite_ids": len(shared_ids),
            "cross_category_shared_sprite_ids": len(cross_category),
            "things_with_shared_sprites": sum(1 for thing in things if thing["shared_sprite_count"] > 0),
            "repaint_strategy_counts": strategy_counts,
            "distinct_structure_signatures": len(shape_counts),
        },
        "things": things,
        "sprite_ownership": [sprite_records[sid] for sid in sorted(sprite_records)],
        "unreferenced_sprite_ids": sorted(all_sprites - referenced),
    }


def write_outputs(payload: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "dat_structure_catalog.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    thing_fields = [
        "category", "id", "owner_ref", "width_blocks", "height_blocks", "real_size",
        "layers", "pattern_x", "pattern_y", "pattern_z", "animation_phases",
        "sprite_ref_slots", "nonzero_sprite_ref_count", "unique_sprite_count",
        "duplicate_ref_slots", "shared_sprite_count", "shared_other_thing_count",
        "repaint_strategy", "safe_to_repaint_with_strategy",
        "attributes_fingerprint_sha256", "shape_fingerprint_sha256",
        "non_sprite_prefix_fingerprint_sha256", "record_fingerprint_sha256",
    ]
    with (out_dir / "dat_things.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=thing_fields)
        writer.writeheader()
        for thing in payload["things"]:
            row = {key: thing.get(key, "") for key in thing_fields}
            row["unique_sprite_count"] = len(thing["unique_sprite_ids"])
            writer.writerow(row)

    sprite_fields = [
        "sprite_id", "owner_count", "reference_slot_count", "shared",
        "cross_category_shared", "categories", "owners",
    ]
    with (out_dir / "sprite_ownership.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sprite_fields)
        writer.writeheader()
        for sprite in payload["sprite_ownership"]:
            writer.writerow({
                "sprite_id": sprite["sprite_id"],
                "owner_count": sprite["owner_count"],
                "reference_slot_count": sprite["reference_slot_count"],
                "shared": sprite["shared"],
                "cross_category_shared": sprite["cross_category_shared"],
                "categories": " | ".join(sprite["categories"]),
                "owners": " | ".join(sprite["owners"]),
            })

    metrics = payload["metrics"]
    header = payload["dat_header"]
    lines = [
        "# RPGGAME DAT/SPR Structural Catalog v1",
        "",
        "Derived structural metadata only. **No sprite pixels are included.**",
        "",
        "## Coverage",
        "",
        f"- DAT things: **{metrics['thing_count']}**",
        f"- Items: **{metrics['category_counts']['item']}**",
        f"- Creatures: **{metrics['category_counts']['creature']}**",
        f"- Protected effects: **{metrics['category_counts']['effect']}**",
        f"- Protected missiles: **{metrics['category_counts']['missile']}**",
        f"- SPR payload slots available: **{payload['spr_header']['sprite_count']}**",
        f"- Unique SPR IDs referenced by DAT: **{metrics['referenced_unique_sprite_ids']}**",
        f"- Shared SPR IDs: **{metrics['shared_sprite_ids']}**",
        f"- Cross-category shared SPR IDs: **{metrics['cross_category_shared_sprite_ids']}**",
        f"- Things touching at least one shared SPR ID: **{metrics['things_with_shared_sprites']}**",
        f"- Distinct render-structure signatures: **{metrics['distinct_structure_signatures']}**",
        "",
        "## Exact pinned DAT namespace",
        "",
        f"- Item IDs: 100–{header['item_max']}",
        f"- Creature looktypes: 1–{header['creature_max']}",
        f"- Effects: 1–{header['effect_max']} (protected)",
        f"- Missiles: 1–{header['missile_max']} (protected)",
        "",
        "## Reskin safety rule",
        "",
        "Each thing carries a SHA-256 fingerprint of its complete non-sprite DAT prefix "
        "(attributes + render topology). A visual-only rewrite must preserve that prefix.",
        "",
        "- Exclusive sprite payloads: direct repaint is structurally isolated.",
        "- Shared sprite payloads: clone the shared sprite, redirect only the intended thing, then repaint the clone.",
        "- Effects/missiles: protected; no repaint in the current scope.",
        "",
        "Known regression probe: item 126 and item 990 must remain detected as sharing at least one sprite payload.",
    ]
    (out_dir / "DAT_STRUCTURE_CATALOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((out_dir / "DAT_STRUCTURE_CATALOG.md").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--otsp-root", type=Path, default=DEFAULT_OTSP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    payload = build_catalog(args.otsp_root)
    write_outputs(payload, args.out)


if __name__ == "__main__":
    main()
