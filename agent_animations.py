"""Deterministic 240x135 screen animations. No downloaded assets or system fonts."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = (240, 135)
FRAME_MS = 160
AGENTS = {"pi": (81, 229, 177), "claude": (232, 155, 111), "codex": (112, 195, 255)}
FRAME_COUNTS = {"start": 8, "finish": 4}
BACKGROUND = (12, 16, 22)


def frame(agent, event, index):
    """Draw at twice the screen resolution for readable small text and curves."""
    accent = AGENTS[agent]
    image = Image.new("RGB", (480, 270), BACKGROUND)
    draw = ImageDraw.Draw(image)
    phase = index / FRAME_COUNTS[event]

    def line(points, fill=accent, width=3):
        draw.line([(round(x * 2), round(y * 2)) for x, y in points], fill=fill,
                  width=width * 2, joint="curve")

    def text(x, y, value, size, color):
        draw.text((x * 2, y * 2), value, font=ImageFont.load_default(size=size * 2), fill=color)

    draw.rounded_rectangle((12, 12, 467, 257), radius=18, outline=(40, 48, 58), width=2)
    text(16, 14, "TIMELESS / AGENTS", 9, (127, 142, 158))
    draw.ellipse((438, 32, 448, 42), fill=accent)
    cx, cy = 52, 69
    if agent == "pi":
        # Pi's two pillars stay readable inside a travelling orbit.
        line([(34, 53), (70, 53)], width=4)
        line([(43, 53), (43, 76), (38, 84)], width=4)
        line([(60, 53), (60, 80), (67, 83)], width=4)
        draw.arc((38, 68, 170, 208), -90 + phase * 360, 150 + phase * 360,
                 fill=accent, width=3)
        angle = phase * math.tau
        x, y = cx + 33 * math.cos(angle), cy + 35 * math.sin(angle)
        draw.ellipse((x * 2 - 5, y * 2 - 5, x * 2 + 5, y * 2 + 5), fill=(228, 255, 245))
    elif agent == "claude":
        # A warm twelve-ray sun pulses around a fixed centre.
        for ray in range(12):
            angle = math.tau * ray / 12 + 0.08 * math.sin(phase * math.tau)
            radius = 28 + 3 * math.sin(phase * math.tau + ray * 0.5)
            line([(cx + 13 * math.cos(angle), cy + 13 * math.sin(angle)),
                  (cx + radius * math.cos(angle), cy + radius * math.sin(angle))], width=3)
        draw.ellipse((94, 128, 114, 148), fill=accent)
    else:
        # A terminal cursor travels between coding brackets.
        line([(39, 52), (25, 69), (39, 86)], width=4)
        line([(65, 52), (79, 69), (65, 86)], width=4)
        line([(57, 48), (47, 90)], fill=(226, 238, 246), width=3)
        y = 47 + int(phase * 43)
        line([(27, y), (77, y)], fill=(51, 90, 118), width=1)

    text(101, 38, agent.upper(), 22, (239, 244, 248))
    text(102, 67, "WORKING" if event == "start" else "DONE", 12, accent)
    if event == "start":
        for dot in range(4):
            color = accent if dot == index % 4 else (45, 55, 65)
            draw.ellipse((204 + dot * 23, 179, 214 + dot * 23, 189), fill=color)
    else:
        line([(105, 92), (110, 97), (120, 86)], width=2)
        text(127, 87, "TURN FINISHED", 8, (153, 171, 184))

    draw.rounded_rectangle((32, 224, 447, 231), radius=3, fill=(37, 46, 56))
    if event == "start":
        x = 32 + round(index / 7 * 345)
        draw.rounded_rectangle((x, 224, x + 70, 231), radius=3, fill=accent)
    else:
        # A subtle travelling highlight keeps the completion card alive.
        draw.rounded_rectangle((32, 224, 447, 231), radius=3, fill=accent)
        x = 32 + round(phase * 330)
        draw.rounded_rectangle((x, 224, x + 70, 231), radius=3, fill=(225, 245, 238))
    return image.resize(SIZE, Image.Resampling.LANCZOS)


def frames(agent, event):
    return [frame(agent, event, i) for i in range(FRAME_COUNTS[event])]


def export(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    sheet = Image.new("RGB", (SIZE[0] * 2, SIZE[1] * len(AGENTS)), BACKGROUND)
    for row, agent in enumerate(AGENTS):
        for column, event in enumerate(FRAME_COUNTS):
            images = frames(agent, event)
            images[0].save(directory / f"{agent}-{event}.gif", save_all=True,
                           append_images=images[1:], duration=FRAME_MS, loop=0,
                           disposal=2, optimize=False)
            sheet.paste(images[0], (column * SIZE[0], row * SIZE[1]))
    sheet.save(directory / "preview.png")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="animations")
    export(parser.parse_args().directory)
