#!/usr/bin/env python3
"""PP-MAP-001 OTSP mapping-language laboratory.

This is a learning/measurement tool, not a town generator.

It builds a visual atlas from the exact pinned OTSP DAT/SPR pair and combines
that with explicit OTSP RME metadata. The output deliberately distinguishes
explicit/editor-authored relationships, broad category membership, and
still-unclassified visual grammar.

Nothing in this tool certifies a wall/door/roof relationship merely because
item IDs are adjacent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

from otsp_humanoid_generator import (
    TILE,
    _Reader,
    _Sprites,
    _parse_thing,
    _sprite_index,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OTSP = ROOT / ".work" / "otsp-source"
DEFAULT_OUT = ROOT / ".work" / "pp_map_001_lab"

PINNED_OTSP_COMMIT = "ae88e1828671b349e729dd21177dde15ea41e123"

MAP_TILESETS = (
    "Grounds",
    "Borders",
    "Walls",
    "Doors and Windows",
    "Roofs",
    "Floor Change",
    "Nature",
    "Stones",
    "Town",
    "Mountains",
)

EVIDENCE_EXPLICIT = "EXPLICIT_OTSP_RME"
EVIDENCE_UNCLASSIFIED = "UNCLASSIFIED"

ATLAS_COLS = 8
ATLAS_ROWS = 8
ATLAS_CELL_W = 120
ATLAS_CELL_H = 104
SPRITE_BOX = 68


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def expand_item_node(node: ET.Element) -> Iterable[int]:
    if "id" in node.attrib:
        yield int(node.attrib["id"])
        return
    if "fromid" in node.attrib:
        start = int(node.attrib["fromid"])
        end = int(node.attrib.get("toid", start))
        yield from range(start, end + 1)


def parse_all_items(dat_path: Path) -> tuple[dict[str, int], dict[int, dict[str, Any]]]:
    reader = _Reader(dat_path.read_bytes())
    header = {
        "signature": reader.u32(),
        "item_max": reader.u16(),
        "creature_max": reader.u16(),
        "effect_max": reader.u16(),
        "missile_max": reader.u16(),
    }

    items: dict[int, dict[str, Any]] = {}
    for iid in range(100, header["item_max"] + 1):
        items[iid] = _parse_thing(reader, iid)

    for cid in range(1, header["creature_max"] + 1):
        _parse_thing(reader, cid)
    for eid in range(1, header["effect_max"] + 1):
        _parse_thing(reader, eid)
    for mid in range(1, header["missile_max"] + 1):
        _parse_thing(reader, mid)

    if reader.pos != len(reader.data):
        raise RuntimeError(f"DAT parse incomplete: {reader.pos}/{len(reader.data)}")
    return header, items


def parse_item_labels(items_xml: Path) -> dict[int, list[str]]:
    root = ET.parse(items_xml).getroot()
    labels: defaultdict[int, set[str]] = defaultdict(set)
    for node in root.findall("item"):
        name = node.attrib.get("name")
        if not name:
            continue
        for iid in expand_item_node(node):
            labels[iid].add(name)
    return {iid: sorted(v) for iid, v in labels.items()}


def parse_tilesets(tilesets_xml: Path) -> tuple[dict[str, list[int]], dict[int, list[str]]]:
    root = ET.parse(tilesets_xml).getroot()
    by_tileset: dict[str, list[int]] = {}
    by_item: defaultdict[int, set[str]] = defaultdict(set)

    for tileset in root.findall("tileset"):
        name = tileset.attrib.get("name", "")
        ids: set[int] = set()
        for section in list(tileset):
            for item in section.findall("item"):
                for iid in expand_item_node(item):
                    ids.add(iid)
                    by_item[iid].add(name)
        by_tileset[name] = sorted(ids)

    return by_tileset, {iid: sorted(v) for iid, v in by_item.items()}


def parse_ground_brushes(grounds_xml: Path) -> list[dict[str, Any]]:
    root = ET.parse(grounds_xml).getroot()
    out: list[dict[str, Any]] = []
    for brush in root.findall("brush"):
        variants = []
        borders = []
        for child in list(brush):
            if child.tag == "item" and "id" in child.attrib:
                variants.append({
                    "id": int(child.attrib["id"]),
                    "chance": int(child.attrib.get("chance", "0") or 0),
                })
            elif child.tag == "border" and "id" in child.attrib:
                borders.append({
                    "id": int(child.attrib["id"]),
                    "align": child.attrib.get("align"),
                })
        out.append({
            "name": brush.attrib.get("name", ""),
            "type": brush.attrib.get("type", ""),
            "server_lookid": int(brush.attrib["server_lookid"]) if brush.attrib.get("server_lookid") else None,
            "z_order": int(brush.attrib["z-order"]) if brush.attrib.get("z-order") else None,
            "variants": variants,
            "borders": borders,
            "evidence": EVIDENCE_EXPLICIT,
            "source": "rme_files/grounds.xml",
        })
    return out


def parse_border_families(borders_xml: Path) -> list[dict[str, Any]]:
    root = ET.parse(borders_xml).getroot()
    out = []
    for border in root.findall("border"):
        pieces = []
        for node in border.findall("borderitem"):
            pieces.append({
                "edge": node.attrib.get("edge"),
                "item": int(node.attrib["item"]),
            })
        out.append({
            "id": int(border.attrib["id"]),
            "group": border.attrib.get("group"),
            "pieces": pieces,
            "evidence": EVIDENCE_EXPLICIT,
            "source": "rme_files/borders.xml",
        })
    return out


def transparent_canvas(width: int, height: int) -> Image.Image:
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


def render_item_thing(
    thing: dict[str, Any],
    sprites: _Sprites,
    *,
    phase: int = 0,
    pattern_x: int = 0,
    pattern_y: int = 0,
    pattern_z: int = 0,
) -> Image.Image:
    """Render one deterministic item appearance from DAT/SPR."""
    width = int(thing["width"])
    height = int(thing["height"])
    layers = int(thing["layers"])
    px_count = int(thing["pattern_x"])
    py_count = int(thing["pattern_y"])
    pz_count = int(thing["pattern_z"])
    phases = int(thing["phases"])

    if not (0 <= pattern_x < px_count):
        raise ValueError("pattern_x out of bounds")
    if not (0 <= pattern_y < py_count):
        raise ValueError("pattern_y out of bounds")
    if not (0 <= pattern_z < pz_count):
        raise ValueError("pattern_z out of bounds")
    if not (0 <= phase < phases):
        raise ValueError("phase out of bounds")

    fw = width * TILE
    fh = height * TILE
    image = transparent_canvas(fw, fh)
    pix = image.load()

    sprite_ids = thing["sprites"]
    assert isinstance(sprite_ids, list)

    for layer in range(layers):
        for h in range(height):
            for w in range(width):
                idx = _sprite_index(
                    thing,
                    w=w,
                    h=h,
                    layer=layer,
                    direction=pattern_x,
                    addon=pattern_y,
                    z=pattern_z,
                    phase=phase,
                )
                sid = int(sprite_ids[idx])
                block = sprites.canvas(sid)
                dx = (width - w - 1) * TILE
                dy = (height - h - 1) * TILE
                for y in range(TILE):
                    for x in range(TILE):
                        rgb = block[y * TILE + x]
                        if rgb is not None:
                            pix[dx + x, dy + y] = (*rgb, 255)
    return image


def image_nonempty(img: Image.Image) -> bool:
    return img.getchannel("A").getbbox() is not None


def paste_center(dst: Image.Image, src: Image.Image, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1
    shown = src
    if src.width > max_w or src.height > max_h:
        ratio = min(max_w / src.width, max_h / src.height)
        shown = src.resize(
            (max(1, round(src.width * ratio)), max(1, round(src.height * ratio))),
            Image.Resampling.NEAREST,
        )
    x = x1 + (max_w - shown.width) // 2
    y = y1 + (max_h - shown.height) // 2
    dst.alpha_composite(shown, (x, y))


def short_label(labels: list[str]) -> str:
    if not labels:
        return ""
    text = labels[0]
    return text if len(text) <= 18 else text[:17] + "…"


def build_atlas_pages(
    *,
    category: str,
    ids: list[int],
    items: dict[int, dict[str, Any]],
    sprites: _Sprites,
    labels: dict[int, list[str]],
    out_dir: Path,
) -> dict[str, Any]:
    pages_dir = out_dir / "atlases"
    pages_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    per_page = ATLAS_COLS * ATLAS_ROWS
    page_count = max(1, math.ceil(len(ids) / per_page))
    blank_ids: list[int] = []
    rendered = 0
    safe_name = category.lower().replace(" ", "_").replace("/", "_").replace("&", "and")

    for page_index in range(page_count):
        page_ids = ids[page_index * per_page:(page_index + 1) * per_page]
        canvas = Image.new(
            "RGBA",
            (ATLAS_COLS * ATLAS_CELL_W, ATLAS_ROWS * ATLAS_CELL_H),
            (28, 30, 34, 255),
        )
        draw = ImageDraw.Draw(canvas)

        for slot, iid in enumerate(page_ids):
            col = slot % ATLAS_COLS
            row = slot // ATLAS_COLS
            x0 = col * ATLAS_CELL_W
            y0 = row * ATLAS_CELL_H
            draw.rectangle(
                (x0 + 1, y0 + 1, x0 + ATLAS_CELL_W - 2, y0 + ATLAS_CELL_H - 2),
                outline=(80, 83, 90, 255),
            )

            thing = items.get(iid)
            if thing is None:
                blank_ids.append(iid)
                draw.text((x0 + 5, y0 + 5), f"{iid} MISSING DAT", fill=(255, 100, 100, 255), font=font)
                continue

            img = render_item_thing(thing, sprites)
            if not image_nonempty(img):
                blank_ids.append(iid)

            paste_center(
                canvas,
                img,
                (
                    x0 + (ATLAS_CELL_W - SPRITE_BOX) // 2,
                    y0 + 5,
                    x0 + (ATLAS_CELL_W + SPRITE_BOX) // 2,
                    y0 + 5 + SPRITE_BOX,
                ),
            )
            draw.text((x0 + 5, y0 + 76), f"ID {iid}", fill=(240, 240, 240, 255), font=font)
            name = short_label(labels.get(iid, []))
            if name:
                draw.text((x0 + 5, y0 + 89), name, fill=(180, 184, 192, 255), font=font)
            rendered += 1

        path = pages_dir / f"{safe_name}_{page_index + 1:02d}.png"
        canvas.convert("RGB").save(path, optimize=True)

    return {
        "category": category,
        "ids": len(ids),
        "rendered_cells": rendered,
        "page_count": page_count,
        "blank_or_missing_ids": sorted(set(blank_ids)),
    }


def border_overlay_sheet(
    family: dict[str, Any],
    *,
    items: dict[int, dict[str, Any]],
    sprites: _Sprites,
    out_dir: Path,
    grass_base: int | None,
) -> dict[str, Any]:
    pieces = family["pieces"]
    cols = 4
    rows = max(1, math.ceil(len(pieces) / cols))
    cell_w = 150
    cell_h = 116
    canvas = Image.new("RGBA", (cols * cell_w, rows * cell_h), (26, 28, 32, 255))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    base_img = None
    if grass_base is not None and grass_base in items:
        candidate = render_item_thing(items[grass_base], sprites)
        if image_nonempty(candidate):
            base_img = candidate

    for i, piece in enumerate(pieces):
        col = i % cols
        row = i // cols
        x0 = col * cell_w
        y0 = row * cell_h
        iid = int(piece["item"])
        edge = piece.get("edge") or "?"
        draw.rectangle((x0 + 1, y0 + 1, x0 + cell_w - 2, y0 + cell_h - 2), outline=(75, 78, 86, 255))

        tile = transparent_canvas(64, 64)
        if base_img is not None:
            paste_center(tile, base_img, (16, 16, 48, 48))
        if iid in items:
            overlay = render_item_thing(items[iid], sprites)
            paste_center(tile, overlay, (16, 16, 48, 48))

        paste_center(canvas, tile, (x0 + 43, y0 + 7, x0 + 107, y0 + 71))
        draw.text((x0 + 6, y0 + 78), f"{edge} = {iid}", fill=(240, 240, 240, 255), font=font)
        draw.text((x0 + 6, y0 + 94), f"border {family['id']}", fill=(175, 180, 190, 255), font=font)

    d = out_dir / "border_role_sheets"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"border_{family['id']:03d}.png"
    canvas.convert("RGB").save(path, optimize=True)
    return {
        "border_id": family["id"],
        "piece_count": len(pieces),
        "path": str(path.relative_to(out_dir)),
        "base_overlay_item": grass_base,
    }


def build_registry(
    *,
    header: dict[str, int],
    source_hashes: dict[str, str],
    ground_brushes: list[dict[str, Any]],
    border_families: list[dict[str, Any]],
    by_tileset: dict[str, list[int]],
    by_item_tilesets: dict[int, list[str]],
) -> dict[str, Any]:
    explicit_ground_ids = {
        int(v["id"])
        for brush in ground_brushes
        for v in brush["variants"]
    }
    explicit_border_item_ids = {
        int(p["item"])
        for family in border_families
        for p in family["pieces"]
    }

    candidate_registry = {}
    for category in MAP_TILESETS:
        ids = by_tileset.get(category, [])
        evidence = EVIDENCE_EXPLICIT if category in {"Grounds", "Borders"} else EVIDENCE_UNCLASSIFIED
        candidate_registry[category] = {
            "ids": ids,
            "count": len(ids),
            "default_evidence": evidence,
            "production_policy": (
                "ONLY_EXPLICIT_OR_SEPARATELY_CERTIFIED"
                if category in {"Grounds", "Borders"}
                else "BLOCK_UNTIL_FAMILY_ORIENTATION_CERTIFIED"
            ),
        }

    return {
        "schema_version": 1,
        "project": "PP-MAP-001",
        "asset_profile": {
            "name": "pocketpvp-otsp-1041-pinned",
            "otsp_repository": "peonso/opentibia_sprite_pack",
            "otsp_commit": PINNED_OTSP_COMMIT,
            "protocol": "10.41",
            "dat_header": header,
            "sha256": source_hashes,
        },
        "evidence_classes": {
            EVIDENCE_EXPLICIT: "relationship appears explicitly in pinned OTSP RME metadata",
            "SOURCE_DERIVED": "derived from pinned implementation/conversion source",
            "EXPERIMENTAL_VISUAL": "verified by controlled rendered/client experiment",
            "EXPERIMENTAL_MECHANICAL": "verified by controlled server/mechanics experiment",
            "POCKETPVP_AUTHORED": "relationship intentionally authored by PocketPVP from verified assets",
            EVIDENCE_UNCLASSIFIED: "not available to production generation",
        },
        "explicit_grammar": {
            "ground_brushes": ground_brushes,
            "border_families": border_families,
            "explicit_ground_item_ids": sorted(explicit_ground_ids),
            "explicit_border_item_ids": sorted(explicit_border_item_ids),
        },
        "candidate_asset_registry": candidate_registry,
        "item_tileset_membership": {
            str(iid): names
            for iid, names in sorted(by_item_tilesets.items())
            if any(name in MAP_TILESETS for name in names)
        },
        "regression_rules": {
            "no_numeric_adjacency_certification": True,
            "no_generic_tile_range_randomization_without_family_evidence": True,
            "unclassified_wall_door_roof_blocked_from_production": True,
            "public_repo_must_not_receive_private_world_layout": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--otsp", type=Path, default=DEFAULT_OTSP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    otsp = args.otsp
    out = args.out
    client = otsp / "client_files"
    rme = otsp / "rme_files"
    server = otsp / "server_files"

    required = [
        client / "otsp.dat",
        client / "otsp.spr",
        rme / "grounds.xml",
        rme / "borders.xml",
        rme / "tilesets.xml",
        rme / "items.xml",
        server / "items.otb",
        server / "items.xml",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("missing pinned OTSP inputs:\n" + "\n".join(missing))

    out.mkdir(parents=True, exist_ok=True)

    source_hashes = {str(p.relative_to(otsp)): sha256_file(p) for p in required}
    header, items = parse_all_items(client / "otsp.dat")
    sprites = _Sprites(client / "otsp.spr")
    labels = parse_item_labels(rme / "items.xml")
    by_tileset, by_item_tilesets = parse_tilesets(rme / "tilesets.xml")
    ground_brushes = parse_ground_brushes(rme / "grounds.xml")
    border_families = parse_border_families(rme / "borders.xml")

    registry = build_registry(
        header=header,
        source_hashes=source_hashes,
        ground_brushes=ground_brushes,
        border_families=border_families,
        by_tileset=by_tileset,
        by_item_tilesets=by_item_tilesets,
    )
    (out / "pp_map_001_registry_seed.json").write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    atlas_reports = []
    for category in MAP_TILESETS:
        ids = [iid for iid in by_tileset.get(category, []) if 100 <= iid <= header["item_max"]]
        atlas_reports.append(
            build_atlas_pages(
                category=category,
                ids=ids,
                items=items,
                sprites=sprites,
                labels=labels,
                out_dir=out,
            )
        )

    grass_base = None
    grass = next((g for g in ground_brushes if g["name"].strip().lower() == "grass"), None)
    if grass and grass["variants"]:
        grass_base = int(grass["variants"][0]["id"])

    border_sheets = [
        border_overlay_sheet(
            fam,
            items=items,
            sprites=sprites,
            out_dir=out,
            grass_base=grass_base if fam["id"] == 1 else None,
        )
        for fam in border_families
    ]

    border1 = next((f for f in border_families if f["id"] == 1), None)
    if border1 is None:
        raise RuntimeError("OTSP explicit border family 1 disappeared")
    expected_roles = ["n", "e", "s", "w", "cnw", "cne", "csw", "cse", "dnw", "dne", "dsw", "dse"]
    got_roles = [p["edge"] for p in border1["pieces"]]
    got_items = [int(p["item"]) for p in border1["pieces"]]
    if got_roles != expected_roles:
        raise RuntimeError(f"OTSP border 1 roles changed: {got_roles}")
    if got_items != list(range(215, 227)):
        raise RuntimeError(f"OTSP border 1 IDs changed: {got_items}")

    if grass is None:
        raise RuntimeError("OTSP grass brush disappeared")
    grass_ids = [int(v["id"]) for v in grass["variants"]]
    if grass_ids != [101, 102, 103, 104, 105]:
        raise RuntimeError(f"OTSP grass variants changed: {grass_ids}")

    blank_map_assets = sorted({
        iid
        for report in atlas_reports
        for iid in report["blank_or_missing_ids"]
    })

    report = {
        "project": "PP-MAP-001",
        "result": "PASS",
        "pinned_otsp_commit": PINNED_OTSP_COMMIT,
        "dat_header": header,
        "sprite_count": sprites.count,
        "explicit_ground_brushes": len(ground_brushes),
        "explicit_border_families": len(border_families),
        "map_tileset_counts": {
            category: len(by_tileset.get(category, []))
            for category in MAP_TILESETS
        },
        "atlas_reports": atlas_reports,
        "border_role_sheets": border_sheets,
        "blank_or_missing_visual_map_assets": blank_map_assets,
        "certification_boundary": {
            "grass_brush_101_105": EVIDENCE_EXPLICIT,
            "border_1_215_226": EVIDENCE_EXPLICIT,
            "other_explicit_border_families": EVIDENCE_EXPLICIT if border_families else EVIDENCE_UNCLASSIFIED,
            "wall_families": EVIDENCE_UNCLASSIFIED,
            "door_wall_pairings": EVIDENCE_UNCLASSIFIED,
            "roof_families": EVIDENCE_UNCLASSIFIED,
        },
    }
    (out / "PP_MAP_001_LAB_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# PP-MAP-001 Mapping Laboratory — Pass A",
        "",
        f"- Pinned OTSP: {PINNED_OTSP_COMMIT}",
        f"- DAT item maximum: {header['item_max']}",
        f"- SPR blocks: {sprites.count}",
        f"- Explicit OTSP ground brushes: {len(ground_brushes)}",
        f"- Explicit OTSP border families: {len(border_families)}",
        "",
        "## Certification boundary",
        "",
        "- Grass 101–105: explicit OTSP RME evidence.",
        "- Border family 1 / 215–226 with named edge roles: explicit OTSP RME evidence.",
        "- Walls: still UNCLASSIFIED as visual families/orientations.",
        "- Door-to-wall pairings: still UNCLASSIFIED.",
        "- Roof families: still UNCLASSIFIED.",
        "- Numeric adjacency alone never certifies a family.",
        "",
        "## Atlas coverage",
        "",
        "| Category | IDs | Pages | blank/missing |",
        "|---|---:|---:|---:|",
    ]
    for rec in atlas_reports:
        lines.append(
            f"| {rec['category']} | {rec['ids']} | {rec['page_count']} | {len(rec['blank_or_missing_ids'])} |"
        )

    lines += [
        "",
        "## Next experiment",
        "",
        "Use the generated contact sheets to cluster wall/door/roof candidates, then build controlled",
        "orientation/junction experiments. Nothing should reach the production generator until those",
        "relationships move out of UNCLASSIFIED.",
        "",
    ]
    (out / "PP_MAP_001_LAB_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
