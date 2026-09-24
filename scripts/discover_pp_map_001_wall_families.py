#!/usr/bin/env python3
"""PP-MAP-001 wall-role discovery.

OTSP ships hundreds of wall sprites but an empty rme_files/walls.xml. This
experiment reconstructs *candidate* basic wall families from rendered geometry.

RME itself gives us the semantic wall language:
- vertical
- horizontal
- pole
- northwest diagonal ("corner")
plus richer end/T/intersection alignments when a brush supplies them.

The first OTSP wall quartet 518..521 is used only as an empirical visual anchor:
the atlas shows the four canonical silhouettes in the same order commonly used
by RME wall sets: vertical, horizontal, pole, corner. Candidate hits remain
EXPERIMENTAL_VISUAL until a composition test passes; they are never promoted
to production solely by numeric adjacency.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from build_pp_map_001_lab import (
    DEFAULT_OTSP,
    DEFAULT_OUT,
    _Sprites,
    parse_all_items,
    parse_tilesets,
    render_item_thing,
)

ROLE_NAMES = ("vertical", "horizontal", "pole", "corner")
ANCHOR_IDS = {
    "vertical": 518,
    "horizontal": 519,
    "pole": 520,
    "corner": 521,
}

EVIDENCE = "EXPERIMENTAL_VISUAL_GEOMETRY"
SOURCE_DERIVED = "SOURCE_DERIVED_RME_TOPOLOGY"

# RME's half/fallback wall vocabulary. Full brushes can add ends, T junctions,
# other diagonals and intersections, but these four roles are sufficient for
# the classic/basic wall grammar.
RME_BASIC_ROLES = {
    "vertical": "WALL_VERTICAL",
    "horizontal": "WALL_HORIZONTAL",
    "pole": "WALL_POLE",
    "corner": "WALL_NORTHWEST_DIAGONAL",
}


def mask_and_features(img):
    a = img.getchannel("A")
    box = a.getbbox()
    if box is None:
        return set(), {"width": 0, "height": 0, "aspect": 0.0, "fill": 0.0, "area": 0}
    crop = a.crop(box)
    width, height = crop.size
    resized = crop.resize((64, 64))
    pix = resized.load()
    mask = {(x, y) for y in range(64) for x in range(64) if pix[x, y] >= 96}
    raw = crop.load()
    area = sum(1 for y in range(height) for x in range(width) if raw[x, y] > 0)
    fill = area / max(1, width * height)
    return mask, {
        "width": width,
        "height": height,
        "aspect": width / max(1, height),
        "fill": fill,
        "area": area,
    }


def iou(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def closeness(a, b, scale):
    return max(0.0, 1.0 - abs(a - b) / max(scale, 1e-9))


def role_similarity(anchor, candidate):
    amask, af = anchor
    cmask, cf = candidate
    silhouette = iou(amask, cmask)
    aspect = closeness(math.log(max(af["aspect"], 1e-6)), math.log(max(cf["aspect"], 1e-6)), 1.0)
    fill = closeness(af["fill"], cf["fill"], 0.55)
    # Silhouette dominates, but preserve the original aspect ratio that the
    # normalized mask intentionally removes.
    return 0.70 * silhouette + 0.20 * aspect + 0.10 * fill


def render_role_sheet(rec, items, sprites, out_dir):
    font = ImageFont.load_default()
    cell_w, cell_h = 180, 150
    canvas = Image.new("RGBA", (cell_w * 4, cell_h), (27, 29, 34, 255))
    draw = ImageDraw.Draw(canvas)

    for idx, role in enumerate(ROLE_NAMES):
        iid = rec["role_map"][role]
        x0 = idx * cell_w
        draw.rectangle((x0 + 1, 1, x0 + cell_w - 2, cell_h - 2), outline=(82, 86, 94, 255))
        img = render_item_thing(items[iid], sprites)
        # Center without smoothing.
        max_w, max_h = 92, 92
        shown = img
        if img.width > max_w or img.height > max_h:
            ratio = min(max_w / img.width, max_h / img.height)
            shown = img.resize((max(1, round(img.width * ratio)), max(1, round(img.height * ratio))), Image.Resampling.NEAREST)
        px = x0 + (cell_w - shown.width) // 2
        py = 8 + (92 - shown.height) // 2
        canvas.alpha_composite(shown, (px, py))
        draw.text((x0 + 7, 105), f"{role}: {iid}", fill=(240, 240, 240, 255), font=font)
        score = rec["role_scores"][role]
        draw.text((x0 + 7, 120), f"score {score:.3f}", fill=(183, 188, 198, 255), font=font)
        draw.text((x0 + 7, 134), rec["evidence"], fill=(150, 155, 166, 255), font=font)

    d = out_dir / "wall_role_candidates"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"candidate_{rec['start_id']:04d}_{rec['start_id']+3:04d}.png"
    canvas.convert("RGB").save(path, optimize=True)
    return str(path.relative_to(out_dir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--otsp", type=Path, default=DEFAULT_OTSP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-mean", type=float, default=0.66)
    ap.add_argument("--min-role", type=float, default=0.48)
    args = ap.parse_args()

    client = args.otsp / "client_files"
    rme = args.otsp / "rme_files"
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    header, items = parse_all_items(client / "otsp.dat")
    sprites = _Sprites(client / "otsp.spr")
    by_tileset, _ = parse_tilesets(rme / "tilesets.xml")
    wall_ids = sorted(i for i in by_tileset.get("Walls", []) if 100 <= i <= header["item_max"])
    wall_set = set(wall_ids)

    anchors = {}
    for role, iid in ANCHOR_IDS.items():
        anchors[role] = mask_and_features(render_item_thing(items[iid], sprites))

    # Sanity-check what the human atlas inspection says about the anchor.
    af = {role: anchors[role][1] for role in ROLE_NAMES}
    if not (af["vertical"]["aspect"] < af["horizontal"]["aspect"]):
        raise RuntimeError(f"wall anchor orientation sanity failed: {af}")
    if not (af["pole"]["area"] < af["vertical"]["area"] and af["pole"]["area"] < af["horizontal"]["area"]):
        raise RuntimeError(f"wall anchor pole sanity failed: {af}")
    if not (af["corner"]["area"] > af["pole"]["area"]):
        raise RuntimeError(f"wall anchor corner sanity failed: {af}")

    candidates = []
    scored_all = []
    for start in wall_ids:
        ids = list(range(start, start + 4))
        if not all(i in wall_set for i in ids):
            continue

        role_map = dict(zip(ROLE_NAMES, ids))
        role_scores = {}
        features = {}
        for role, iid in role_map.items():
            candidate = mask_and_features(render_item_thing(items[iid], sprites))
            role_scores[role] = role_similarity(anchors[role], candidate)
            features[role] = candidate[1]

        scores = list(role_scores.values())
        rec = {
            "start_id": start,
            "ids": ids,
            "role_map": role_map,
            "role_scores": role_scores,
            "mean_score": sum(scores) / 4.0,
            "min_score": min(scores),
            "features": features,
            "evidence": EVIDENCE,
            "production_semantics": "UNCLASSIFIED",
        }
        scored_all.append(rec)
        if rec["mean_score"] >= args.min_mean and rec["min_score"] >= args.min_role:
            candidates.append(rec)

    candidates.sort(key=lambda r: (-r["mean_score"], -r["min_score"], r["start_id"]))
    scored_all.sort(key=lambda r: (-r["mean_score"], -r["min_score"], r["start_id"]))

    # Anchor must rediscover itself exactly.
    anchor_rec = next((r for r in candidates if r["start_id"] == 518), None)
    if anchor_rec is None:
        raise RuntimeError("wall anchor 518..521 was not rediscovered")
    for role, score in anchor_rec["role_scores"].items():
        if abs(score - 1.0) > 1e-9:
            raise RuntimeError(f"wall anchor role {role} score changed: {score}")

    # Avoid flooding the artifact with overlapping marginal hits. Keep all
    # scores in JSON, but render only the strongest candidates.
    rendered = []
    for rec in candidates[:40]:
        rec["sheet"] = render_role_sheet(rec, items, sprites, out)
        rendered.append(rec["start_id"])

    # Source-derived topology contract from RME wall_brush.cpp / brush_tables.cpp.
    topology = {
        "evidence": SOURCE_DERIVED,
        "source_repository": "peonso/rme",
        "source_files": [
            "source/wall_brush.cpp",
            "source/brush_tables.cpp",
            "source/brush_enums.h",
        ],
        "cardinal_neighbor_mask_order": ["north", "west", "east", "south"],
        "full_alignment_count": 16,
        "basic_fallback_roles": RME_BASIC_ROLES,
        "notes": [
            "RME computes a 4-neighbor wall mask.",
            "It first requests the full 16-way alignment.",
            "If the brush lacks that alignment, it retries a half/basic alignment.",
            "Classic brushes therefore remain coherent with vertical/horizontal/pole/corner only.",
        ],
    }

    payload = {
        "project": "PP-MAP-001",
        "method": "role-by-role rendered alpha geometry against empirical OTSP anchor 518..521",
        "anchor": {
            "ids": ANCHOR_IDS,
            "evidence": "EXPERIMENTAL_VISUAL_MANUAL_ANCHOR",
            "production_semantics": "UNCLASSIFIED",
        },
        "rme_topology_contract": topology,
        "thresholds": {"min_mean": args.min_mean, "min_role": args.min_role},
        "candidate_count": len(candidates),
        "rendered_candidate_starts": rendered,
        "candidates": candidates,
        "top_80_scored_windows": scored_all[:80],
        "warning": (
            "A geometry candidate is not a certified material family. It must pass composition "
            "and, where relevant, door/portal/mechanical tests before production use."
        ),
    }
    (out / "wall_geometry_candidates.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "rme_wall_topology_contract.json").write_text(
        json.dumps(topology, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"wall geometry candidates: {len(candidates)}")
    for rec in candidates[:40]:
        print(
            f"{rec['start_id']:4d}-{rec['start_id']+3:4d} "
            f"mean={rec['mean_score']:.3f} min={rec['min_score']:.3f} "
            f"roles={rec['role_map']}"
        )


if __name__ == "__main__":
    main()
