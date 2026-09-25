#!/usr/bin/env python3
"""Build PocketPVP V7 licensed visual payload from pinned OTSP without repainting.

V7 deliberately stops the earlier generated/reskinned sprite path. The output
DAT/SPR are byte-for-byte copies of the pinned OpenTibia Sprite Pack client
files. This script only verifies that the frozen vertical-slice IDs exist and
records their render structure plus the exact OTSP effect definitions used by
the runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from build_dat_structure_catalog import build_catalog as build_dat_catalog

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OTSP = ROOT / ".work" / "otsp-source"
DEFAULT_OUT = ROOT / ".work" / "pocketpvp_live_assets_v1"

OTSP_SHA = "ae88e1828671b349e729dd21177dde15ea41e123"

ITEM_IDS = (
    101, 102, 103, 104, 105,
    *range(215, 227),
    189, 190, 508,
    651, 652, 653, 657,
    660, 661, 662, 663, 664, 668,
    1677, 2099,
)
OUTFIT_IDS = (17, 18)
EFFECT_IDS = (1, 3)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def thing_snapshot(by_ref: dict[str, dict[str, Any]], ref: str) -> dict[str, Any]:
    thing = by_ref.get(ref)
    if thing is None:
        raise RuntimeError(f"missing OTSP thing: {ref}")
    return {
        "owner_ref": ref,
        "width_blocks": int(thing["width_blocks"]),
        "height_blocks": int(thing["height_blocks"]),
        "layers": int(thing["layers"]),
        "pattern_x": int(thing["pattern_x"]),
        "pattern_y": int(thing["pattern_y"]),
        "pattern_z": int(thing["pattern_z"]),
        "animation_phases": int(thing["animation_phases"]),
        "sprite_ref_slots": int(thing["sprite_ref_slots"]),
        "ordered_sprite_refs": [int(v) for v in thing["ordered_sprite_refs"]],
    }


def build(out_dir: Path, otsp_root: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dat_in = otsp_root / "client_files" / "otsp.dat"
    spr_in = otsp_root / "client_files" / "otsp.spr"
    if not dat_in.is_file() or not spr_in.is_file():
        raise SystemExit("missing pinned OTSP DAT/SPR")

    dat_out = out_dir / "Tibia.dat"
    spr_out = out_dir / "Tibia.spr"
    shutil.copyfile(dat_in, dat_out)
    shutil.copyfile(spr_in, spr_out)

    source_dat = sha256_file(dat_in)
    source_spr = sha256_file(spr_in)
    output_dat = sha256_file(dat_out)
    output_spr = sha256_file(spr_out)
    if source_dat != output_dat or source_spr != output_spr:
        raise RuntimeError("licensed OTSP passthrough changed DAT/SPR bytes")

    catalog = build_dat_catalog(otsp_root)
    by_ref = {t["owner_ref"]: t for t in catalog["things"]}

    items = {str(iid): thing_snapshot(by_ref, f"item:{iid}") for iid in ITEM_IDS}
    outfits = {str(iid): thing_snapshot(by_ref, f"outfit:{iid}") for iid in OUTFIT_IDS}
    effects = {str(iid): thing_snapshot(by_ref, f"effect:{iid}") for iid in EFFECT_IDS}

    cert = {
        "schema_version": 2,
        "proof_id": "POCKETPVP_LICENSED_SLICE_V1",
        "result": "PASS",
        "source": {
            "repository": "peonso/opentibia_sprite_pack",
            "commit": OTSP_SHA,
            "license": "CC-BY-4.0",
            "dat_sha256": source_dat,
            "spr_sha256": source_spr,
        },
        "output": {
            "dat_sha256": output_dat,
            "spr_sha256": output_spr,
        },
        "frozen_manifest": {
            "item_ids": list(ITEM_IDS),
            "outfit_ids": list(OUTFIT_IDS),
            "effect_ids": list(EFFECT_IDS),
        },
        "structures": {
            "items": items,
            "outfits": outfits,
            "effects": effects,
        },
        "contracts": {
            "licensed_source_passthrough": True,
            "pixels_modified": False,
            "dat_modified": False,
            "spr_modified": False,
            "custom_sprite_generation_used": False,
            "historical_tibia_pixels_imported": False,
            "mechanics_modified": False,
        },
    }
    (out_dir / "pocketpvp_live_asset_certification.json").write_text(
        json.dumps(cert, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(cert, indent=2, sort_keys=True))
    return cert


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--otsp-root", type=Path, default=DEFAULT_OTSP)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = p.parse_args()
    build(a.out, a.otsp_root)


if __name__ == "__main__":
    main()
