"""Timeless82 animation upload and slot selection over the existing HID transport.

Protocol: https://gist.github.com/jeisinger/b198a72c5d7d203541c6269508c9ad8c
Copyright 2025 Jochen Eisinger, 2026 Fajar Ulin Nuha. See LICENSE, BSD-3-Clause.
"""
import hashlib
import json

from agent_animations import AGENTS, FRAME_MS, SIZE, frames
from kbd_time_sync import Kbd, STATE_DIR, set_clock

FRAME_BYTES = 65536
MAX_FRAMES = 36
DISPLAY_OFFSET = 33
FRAME_OFFSETS = (34, 46)
DELAY_OFFSET = 43


def encode_frame(image):
    if image.size != SIZE:
        raise ValueError(f"screen frames must be {SIZE[0]}x{SIZE[1]}")
    result = bytearray(FRAME_BYTES)
    pixels = image.convert("RGB").tobytes()
    for index, (red, green, blue) in enumerate(zip(pixels[0::3], pixels[1::3], pixels[2::3])):
        pixel = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
        result[index * 2:index * 2 + 2] = pixel.to_bytes(2, "big")
    return bytes(result)


def animation_data():
    """Pack every animation once. Slot 2 starts after slot 1's frame count.

    Selecting an animation changes that boundary and slot 2's frame count,
    exposing only the desired consecutive frames without another flash upload.
    """
    chunks, windows = [], {}
    offset = 0
    for agent in AGENTS:
        for event in ("start", "finish"):
            images = frames(agent, event)
            # The first animation uses slot 1; later animations use slot 2.
            windows[agent, event] = (1, len(images), 0) if offset == 0 else (2, offset, len(images))
            chunks.extend(encode_frame(image) for image in images)
            offset += len(images)
    if offset > MAX_FRAMES:
        raise ValueError(f"animation bank exceeds {MAX_FRAMES} frames")
    first_key = next(iter(windows))
    display, first, _ = windows[first_key]
    windows[first_key] = (display, first, offset - first)
    return b"".join(chunks), windows


def upload(keyboard, data, counts, cfg, progress=None):
    if min(counts) < 1 or sum(counts) > MAX_FRAMES or len(data) != sum(counts) * FRAME_BYTES:
        raise ValueError("invalid animation data or frame counts, maximum 36 total")
    cfg = list(cfg)
    if len(cfg) != 48:
        raise ValueError("expected 48-byte keyboard config")
    for offset, count in zip(FRAME_OFFSETS, counts):
        cfg[offset] = count
    cfg[DELAY_OFFSET:DELAY_OFFSET + 2] = FRAME_MS.to_bytes(2, "little")
    set_clock(cfg)
    keyboard.write_config(cfg)
    keyboard.cmd(0x23)
    keyboard.cmd(1)
    for position in range(0, len(data), 56):
        keyboard.cmd(0x21, data[position:position + 56], position)
        if progress and position % (56 * 500) == 0:
            progress(position, len(data))
    keyboard.cmd(2)


def show_agent(agent, event, force=False, progress=None):
    data, windows = animation_data()
    digest = hashlib.sha256(data).hexdigest()
    cache_file = STATE_DIR / "screen.json"
    with Kbd() as keyboard:
        cfg = keyboard.load_config()
        if len(cfg) != 48:
            raise ValueError("expected 48-byte keyboard config")
        try:
            cache = json.loads(cache_file.read_text())
        except (OSError, ValueError):
            cache = {}
        identity = keyboard.path.decode(errors="replace")
        if (force or cache.get("device") != identity or cache.get("sha256") != digest
                or cache.get("counts") != [cfg[offset] for offset in FRAME_OFFSETS]):
            # Invalidate first. An interrupted upload must always be retried in full.
            cache_file.unlink(missing_ok=True)
            _, first, second = next(iter(windows.values()))
            upload(keyboard, data, (first, second), cfg, progress)
            cfg = keyboard.load_config()
        display, first, second = windows[agent, event]
        cfg[DISPLAY_OFFSET], cfg[34], cfg[46] = display, first, second
        cfg[DELAY_OFFSET:DELAY_OFFSET + 2] = FRAME_MS.to_bytes(2, "little")
        set_clock(cfg)
        keyboard.write_config(cfg)
        cache_file.write_text(json.dumps({"device": identity, "sha256": digest, "counts": [first, second]}))


def show_clock():
    with Kbd() as keyboard:
        cfg = keyboard.load_config()
        if len(cfg) != 48:
            raise ValueError("expected 48-byte keyboard config")
        cfg[DISPLAY_OFFSET] = 0
        set_clock(cfg)
        keyboard.write_config(cfg)
