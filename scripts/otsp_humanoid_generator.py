#!/usr/bin/env python3
"""OTSP-derived humanoid reference generator for RPGGAME.

Reads the pinned OpenTibia Sprite Pack DAT/SPR files and converts selected
CC BY 4.0 outfit templates into RPGGAME role variants. Output is a sequence
of 32x32 sprite blocks ready for a protocol-860 2x2 render ThingType.

Important: 2x2 here is a *render envelope*. RPGGAME logical occupancy remains
one 32x32 map tile.
"""
from __future__ import annotations

from pathlib import Path

TILE = 32
FRAME = 64
ENGINE_DIRECTIONS = ("N", "E", "S", "W")
ANIMATION_PHASES = 3

RGB = tuple[int, int, int]
Pixel = RGB | None
Canvas = list[Pixel]

ROLE_LOOKTYPES = {
    "player": 17,
    "guard": 18,
    "civilian": 20,
    # RPGGAME Orc reuses the measured armored humanoid pose grammar only.
    # Palette, identity, combat role, footprint and mechanics remain RPGGAME-owned.
    "orc": 18,
}

ROLE_COLORS: dict[str, dict[str, RGB]] = {
    "player": {
        "head": (103, 64, 35),
        "body": (55, 76, 92),
        "legs": (91, 59, 37),
        "feet": (54, 38, 29),
    },
    "guard": {
        "head": (91, 62, 39),
        "body": (55, 69, 91),
        "legs": (80, 84, 82),
        "feet": (47, 36, 29),
    },
    "civilian": {
        "head": (116, 74, 42),
        "body": (78, 94, 58),
        "legs": (125, 106, 75),
        "feet": (60, 43, 30),
    },
    "orc": {
        "head": (82, 119, 65),
        "body": (73, 87, 53),
        "legs": (91, 60, 38),
        "feet": (44, 34, 27),
    },
}

_MASKS = {
    (255, 0, 0): "head",
    (0, 255, 0): "body",
    (0, 0, 255): "legs",
    (255, 255, 0): "feet",
}

_ATTR_DISPLACEMENT = 24
_ATTR_LIGHT = 21
_ATTR_MARKET = 33
_U16_ATTRS = {34, 0, 8, 9, 28, 32, 29, 25}


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def u8(self) -> int:
        value = self.data[self.pos]
        self.pos += 1
        return value

    def u16(self) -> int:
        value = int.from_bytes(self.data[self.pos:self.pos + 2], "little")
        self.pos += 2
        return value

    def u32(self) -> int:
        value = int.from_bytes(self.data[self.pos:self.pos + 4], "little")
        self.pos += 4
        return value

    def string(self) -> bytes:
        length = self.u16()
        value = self.data[self.pos:self.pos + length]
        self.pos += length
        return value


def _skip_attrs(reader: _Reader) -> None:
    while True:
        raw = reader.u8()
        if raw == 0xFF:
            return
        attr = 253 if raw == 16 else raw - 1 if raw > 16 else raw
        if attr == _ATTR_DISPLACEMENT:
            reader.u16(); reader.u16()
        elif attr == _ATTR_LIGHT:
            reader.u16(); reader.u16()
        elif attr == _ATTR_MARKET:
            reader.u16(); reader.u16(); reader.u16(); reader.string(); reader.u16(); reader.u16()
        elif attr in _U16_ATTRS:
            reader.u16()


def _parse_thing(reader: _Reader, cid: int) -> dict[str, int | list[int]]:
    _skip_attrs(reader)
    width = reader.u8()
    height = reader.u8()
    real_size = reader.u8() if width > 1 or height > 1 else TILE
    layers = reader.u8()
    pattern_x = reader.u8()
    pattern_y = reader.u8()
    pattern_z = reader.u8()
    phases = reader.u8()
    count = width * height * layers * pattern_x * pattern_y * pattern_z * phases
    sprite_ids = [reader.u32() for _ in range(count)]
    return {
        "id": cid,
        "width": width,
        "height": height,
        "real_size": real_size,
        "layers": layers,
        "pattern_x": pattern_x,
        "pattern_y": pattern_y,
        "pattern_z": pattern_z,
        "phases": phases,
        "sprites": sprite_ids,
    }


def _load_creatures(dat_path: Path) -> dict[int, dict[str, int | list[int]]]:
    reader = _Reader(dat_path.read_bytes())
    _signature = reader.u32()
    item_max = reader.u16()
    creature_max = reader.u16()
    effect_max = reader.u16()
    missile_max = reader.u16()

    for cid in range(100, item_max + 1):
        _parse_thing(reader, cid)

    creatures: dict[int, dict[str, int | list[int]]] = {}
    for cid in range(1, creature_max + 1):
        creatures[cid] = _parse_thing(reader, cid)

    for cid in range(1, effect_max + 1):
        _parse_thing(reader, cid)
    for cid in range(1, missile_max + 1):
        _parse_thing(reader, cid)
    if reader.pos != len(reader.data):
        raise RuntimeError(f"OTSP DAT parse did not consume the file: {reader.pos}/{len(reader.data)}")
    return creatures


class _Sprites:
    def __init__(self, path: Path) -> None:
        self.data = path.read_bytes()
        if len(self.data) < 8:
            raise RuntimeError("OTSP SPR file is truncated")
        self.count = int.from_bytes(self.data[4:8], "little")
        self.table_offset = 8

    def canvas(self, sprite_id: int) -> Canvas:
        out: Canvas = [None] * (TILE * TILE)
        if sprite_id <= 0 or sprite_id > self.count:
            return out

        table_pos = self.table_offset + (sprite_id - 1) * 4
        offset = int.from_bytes(self.data[table_pos:table_pos + 4], "little")
        if offset == 0:
            return out

        pos = offset + 3
        encoded_size = int.from_bytes(self.data[pos:pos + 2], "little")
        pos += 2
        end = pos + encoded_size
        pixel_index = 0

        while pos < end and pixel_index < TILE * TILE:
            transparent = int.from_bytes(self.data[pos:pos + 2], "little")
            colored = int.from_bytes(self.data[pos + 2:pos + 4], "little")
            pos += 4
            pixel_index += transparent
            for _ in range(colored):
                if pixel_index >= TILE * TILE or pos + 3 > end:
                    break
                out[pixel_index] = (self.data[pos], self.data[pos + 1], self.data[pos + 2])
                pos += 3
                pixel_index += 1
        return out


def _sprite_index(
    thing: dict[str, int | list[int]],
    *,
    w: int,
    h: int,
    layer: int,
    direction: int,
    addon: int,
    z: int,
    phase: int,
) -> int:
    width = int(thing["width"])
    height = int(thing["height"])
    layers = int(thing["layers"])
    pattern_x = int(thing["pattern_x"])
    pattern_y = int(thing["pattern_y"])
    pattern_z = int(thing["pattern_z"])
    index = w + h * width
    index += layer * width * height
    index += direction * width * height * layers
    index += addon * width * height * layers * pattern_x
    index += z * width * height * layers * pattern_x * pattern_y
    index += phase * width * height * layers * pattern_x * pattern_y * pattern_z
    return index


def _compose_layer(
    thing: dict[str, int | list[int]],
    sprites: _Sprites,
    *,
    layer: int,
    direction: int,
    phase: int,
    addon: int = 0,
) -> tuple[int, int, Canvas]:
    width = int(thing["width"])
    height = int(thing["height"])
    frame_width = width * TILE
    frame_height = height * TILE
    frame: Canvas = [None] * (frame_width * frame_height)
    sprite_ids = thing["sprites"]
    assert isinstance(sprite_ids, list)

    for h in range(height):
        for w in range(width):
            index = _sprite_index(
                thing,
                w=w,
                h=h,
                layer=layer,
                direction=direction,
                addon=addon,
                z=0,
                phase=phase,
            )
            block = sprites.canvas(int(sprite_ids[index]))
            dx = (width - w - 1) * TILE
            dy = (height - h - 1) * TILE
            for y in range(TILE):
                for x in range(TILE):
                    pixel = block[y * TILE + x]
                    if pixel is not None:
                        frame[(dy + y) * frame_width + dx + x] = pixel
    return frame_width, frame_height, frame


def _shade(base: RGB, target: RGB) -> RGB:
    r, g, b = base
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    factor = max(0.35, min(1.35, 0.35 + lum * 1.25))
    return tuple(max(0, min(255, round(channel * factor))) for channel in target)  # type: ignore[return-value]


def _colorize(base: Canvas, mask: Canvas, colors: dict[str, RGB]) -> Canvas:
    if len(base) != len(mask):
        raise ValueError("OTSP base/mask frame sizes disagree")
    out = list(base)
    for i, mask_pixel in enumerate(mask):
        if mask_pixel is None:
            continue
        region = _MASKS.get(mask_pixel)
        if region is None:
            continue
        base_pixel = base[i]
        if base_pixel is None:
            continue
        out[i] = _shade(base_pixel, colors[region])
    return out


def _orcify(frame: Canvas, direction: int) -> Canvas:
    """Create a direction-aware non-human Orc silhouette inside the GR-024 envelope."""
    if len(frame) != FRAME * FRAME:
        raise ValueError("Orc silhouette transform expects a 64x64 frame")
    if direction not in range(4):
        raise ValueError(f"Orc direction index out of range: {direction}")

    out = list(frame)
    occupied = [
        (i % FRAME, i // FRAME)
        for i, pixel in enumerate(frame)
        if pixel is not None
    ]
    if not occupied:
        return out

    min_x = min(x for x, _ in occupied)
    max_x = max(x for x, _ in occupied)
    min_y = min(y for _, y in occupied)
    max_y = max(y for _, y in occupied)
    silhouette_h = max(1, max_y - min_y + 1)

    def put(x: int, y: int, color: RGB) -> None:
        if 0 <= x < FRAME and 0 <= y < FRAME:
            out[y * FRAME + x] = color

    def span(y1: int, y2: int) -> tuple[int, int, int, int]:
        points = [
            (x, y)
            for y in range(max(min_y, y1), min(max_y, y2) + 1)
            for x in range(FRAME)
            if frame[y * FRAME + x] is not None
        ]
        if not points:
            return min_x, max_x, min_y, min_y
        return (
            min(x for x, _ in points),
            max(x for x, _ in points),
            min(y for _, y in points),
            max(y for _, y in points),
        )

    # Use local upper-body bands rather than whole-frame bounds so a shield,
    # weapon or armor overhang cannot accidentally become the "head".
    head_bottom_hint = min_y + max(8, silhouette_h // 3)
    head_left, head_right, head_top, head_bottom = span(min_y, head_bottom_hint)
    shoulder_top = min_y + max(8, silhouette_h // 3)
    shoulder_bottom = min(max_y - 5, min_y + max(14, (silhouette_h * 3) // 5))

    # Heavy-role read from GR-017: low/wide mass before palette is considered.
    for y in range(shoulder_top, shoulder_bottom + 1):
        xs = [x for x in range(FRAME) if frame[y * FRAME + x] is not None]
        if not xs:
            continue
        left, right = min(xs), max(xs)
        left_color = frame[y * FRAME + left]
        right_color = frame[y * FRAME + right]
        spread_max = 3 if shoulder_top + 2 <= y <= shoulder_bottom - 2 else 2
        for spread in range(1, spread_max + 1):
            if left_color is not None:
                put(left - spread, y, left_color)
            if right_color is not None:
                put(right + spread, y, right_color)

    head_color = ROLE_COLORS["orc"]["head"]
    body_color = ROLE_COLORS["orc"]["body"]
    ivory: RGB = (211, 199, 158)
    shadow: RGB = tuple(max(0, round(channel * 0.58)) for channel in head_color)  # type: ignore[assignment]
    center_x = (head_left + head_right) // 2
    ear_y = min(head_bottom, head_top + max(3, (head_bottom - head_top) // 2))
    jaw_y = min(FRAME - 2, head_bottom + 1)

    # A hunched neck/upper-back wedge keeps the head seated into the shoulder
    # mass rather than reading as an ordinary upright human torso.
    for dx in (-2, -1, 0, 1, 2):
        put(center_x + dx, min(FRAME - 1, shoulder_top), body_color)

    if direction == 2:  # South / front
        for step in (1, 2, 3):
            put(head_left - step, ear_y + (step // 2), head_color)
            put(head_right + step, ear_y + (step // 2), head_color)
        for x in range(center_x - 4, center_x + 5):
            put(x, jaw_y, head_color)
        for x in (center_x - 3, center_x + 3):
            put(x, jaw_y, ivory)
            put(x, jaw_y + 1, ivory)
        put(center_x - 2, max(head_top, jaw_y - 3), shadow)
        put(center_x + 2, max(head_top, jaw_y - 3), shadow)

    elif direction == 0:  # North / back
        # Ear tips and a broad nape are visible; front-facing tusks are not.
        for step in (1, 2, 3):
            put(head_left - step, ear_y + (step // 2), head_color)
            put(head_right + step, ear_y + (step // 2), head_color)
        for x in range(center_x - 4, center_x + 5):
            put(x, jaw_y, body_color)
        for x in range(center_x - 2, center_x + 3):
            put(x, max(head_top, ear_y - 2), shadow)

    elif direction == 1:  # East / right profile
        for step in (1, 2, 3):
            put(head_left - step, ear_y + (step // 2), head_color)
        snout_x = min(FRAME - 2, head_right + 2)
        put(head_right + 1, jaw_y - 1, head_color)
        put(snout_x, jaw_y, head_color)
        put(snout_x, jaw_y + 1, ivory)
        put(head_left - 2, ear_y, shadow)

    else:  # West / left profile
        for step in (1, 2, 3):
            put(head_right + step, ear_y + (step // 2), head_color)
        snout_x = max(1, head_left - 2)
        put(head_left - 1, jaw_y - 1, head_color)
        put(snout_x, jaw_y, head_color)
        put(snout_x, jaw_y + 1, ivory)
        put(head_right + 2, ear_y, shadow)

    return out

def _split_frame(width: int, height: int, frame: Canvas) -> list[Canvas]:
    if width != 2 or height != 2:
        raise RuntimeError(f"RPGGAME P0 humanoid template must be 2x2, got {width}x{height}")
    frame_width = width * TILE
    parts: list[Canvas] = []
    for h in range(height):
        for w in range(width):
            sx = (width - w - 1) * TILE
            sy = (height - h - 1) * TILE
            block: Canvas = [None] * (TILE * TILE)
            for y in range(TILE):
                src = (sy + y) * frame_width + sx
                block[y * TILE:(y + 1) * TILE] = frame[src:src + TILE]
            parts.append(block)
    return parts


def build_humanoid_parts(seed_dir: Path, role: str) -> list[Canvas]:
    """Return 48 32x32 blocks: 3 phases x N/E/S/W x 2x2 blocks."""
    if role not in ROLE_LOOKTYPES:
        raise ValueError(f"unknown RPGGAME humanoid role: {role}")

    dat_path = seed_dir / "otsp.dat"
    spr_path = seed_dir / "otsp.spr"
    if not dat_path.is_file() or not spr_path.is_file():
        raise RuntimeError(
            "Missing pinned OTSP DAT/SPR reference files. Copy client_files/otsp.dat "
            "and client_files/otsp.spr into .work/otsp_seed before generation."
        )

    creatures = _load_creatures(dat_path)
    looktype = ROLE_LOOKTYPES[role]
    thing = creatures[looktype]
    if int(thing["width"]) != 2 or int(thing["height"]) != 2:
        raise RuntimeError(f"OTSP looktype {looktype} render envelope changed")
    if int(thing["layers"]) < 2:
        raise RuntimeError(f"OTSP looktype {looktype} no longer has a color-mask layer")
    if int(thing["pattern_x"]) < 4 or int(thing["phases"]) < ANIMATION_PHASES:
        raise RuntimeError(f"OTSP looktype {looktype} direction/animation grammar changed")

    sprites = _Sprites(spr_path)
    output: list[Canvas] = []
    for phase in range(ANIMATION_PHASES):
        for direction in range(4):
            width, height, base = _compose_layer(
                thing, sprites, layer=0, direction=direction, phase=phase, addon=0
            )
            mw, mh, mask = _compose_layer(
                thing, sprites, layer=1, direction=direction, phase=phase, addon=0
            )
            if (width, height) != (mw, mh):
                raise RuntimeError("OTSP base/mask envelope mismatch")
            frame = _colorize(base, mask, ROLE_COLORS[role])
            if role == "orc":
                frame = _orcify(frame, direction)
            output.extend(_split_frame(width // TILE, height // TILE, frame))

    if len(output) != 48:
        raise RuntimeError(f"expected 48 humanoid blocks, got {len(output)}")
    return output


def get_role_metadata(role: str) -> dict[str, int | str]:
    return {
        "role": role,
        "looktype": ROLE_LOOKTYPES[role],
        "logical_footprint_tiles": 1,
        "render_width_px": FRAME,
        "render_height_px": FRAME,
        "render_blocks_w": 2,
        "render_blocks_h": 2,
        "directions": 4,
        "animation_phases": ANIMATION_PHASES,
        "silhouette_variant": "direction_aware_low_wide_shoulders_ears_profile_snout_tusks" if role == "orc" else "reference_humanoid",
    }
