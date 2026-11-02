#!/usr/bin/env python3
"""Generate 8 x 50px horizontal impact sheets using the original native tile grain.

Requires Pillow: python -m pip install Pillow
Run from any directory: python verification/generate_impact_art.py
Frames 0..7 play once over 0.4s; frame 7 is opaque rubble / molten residue
on a transparent background, held and blinked by the renderer until 2.5s.
Original Rock1.jpg and Lava1.jpg are never modified.
"""

from math import sin, pi
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
BLOCKS = ROOT / "godot/assets/Resources/Blocks"
OUTPUT = ROOT / "godot/assets"
SIZE = 50
FRAMES = 8
ROCK_EDGE = (55, 48, 48, 255)
ROCK_LIGHT = (173, 163, 161, 255)
LAVA_EDGE = (90, 28, 17, 255)


def canvas():
    return Image.new("RGBA", (SIZE, SIZE))


def texture_shape(texture, points, edge, highlight=None):
    mask = Image.new("L", (SIZE, SIZE))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    image = canvas()
    image.paste(texture, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    draw.line(points + points[:1], fill=edge, width=1)
    if highlight:
        draw.line(points[:3], fill=highlight, width=1)
    return image


def rock_frames():
    texture = ImageOps.posterize(Image.open(BLOCKS / "Rock1.jpg").convert("RGB"), 5).convert("RGBA")
    silhouette = [(7, 16), (10, 9), (18, 5), (29, 4), (38, 8), (44, 17),
                  (45, 29), (41, 39), (33, 44), (17, 45), (8, 40), (5, 29)]
    intact = texture_shape(texture, silhouette, ROCK_EDGE)
    # Matching fault edges divide the original boulder into seven actual textured shards.
    polygons = [
        [(7, 16), (10, 9), (18, 5), (24, 5), (23, 17), (17, 23), (6, 24)],
        [(24, 5), (29, 4), (38, 8), (43, 15), (35, 23), (23, 17)],
        [(43, 15), (44, 17), (45, 29), (41, 34), (32, 30), (35, 23)],
        [(23, 17), (35, 23), (32, 30), (24, 34), (16, 30), (17, 23)],
        [(6, 24), (17, 23), (16, 30), (18, 40), (11, 42), (8, 40), (5, 29)],
        [(16, 30), (24, 34), (27, 44), (17, 45), (11, 42), (18, 40)],
        [(32, 30), (41, 34), (41, 39), (33, 44), (27, 44), (24, 34)],
    ]
    destinations = [(8, 39), (19, 39), (40, 39), (28, 37), (4, 44), (16, 44), (34, 44)]
    rotations = [-32, 19, -38, 25, -20, 14, 33]
    shards = []
    for polygon in polygons:
        image = texture_shape(texture, polygon, ROCK_EDGE, ROCK_LIGHT)
        box = image.getbbox()
        shards.append((image.crop(box), ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)))
    frames = [intact]
    cracked = intact.copy()
    draw = ImageDraw.Draw(cracked)
    for fault in [[(24, 6), (23, 17), (17, 23), (16, 30), (18, 40)],
                  [(23, 17), (35, 23), (32, 30), (24, 34), (27, 43)],
                  [(35, 23), (42, 16)], [(32, 30), (41, 34)],
                  [(17, 23), (7, 24)]]:
        draw.line(fault, fill=(43, 36, 36, 255), width=2)
        draw.line([(x + 1, y) for x, y in fault], fill=(156, 144, 141, 255), width=1)
    frames.append(cracked)
    for frame in range(2, FRAMES):
        t = (frame - 1) / 6
        image = canvas()
        draw = ImageDraw.Draw(image)
        if frame >= 4:
            draw.ellipse((3, 42, 46, 47), fill=(47, 39, 34, 115))
        for index, (shard, start) in enumerate(shards):
            end = destinations[index]
            x = start[0] + (end[0] - start[0]) * min(1, t * 1.5)
            y = start[1] + (end[1] - start[1]) * t - sin(t * pi) * (9 if index < 4 else 5)
            width = max(3, round(shard.width * (1 - 0.22 * t)))
            height = max(3, round(shard.height * (1 - 0.40 * t)))
            piece = shard.resize((width, height), Image.Resampling.NEAREST)
            piece = piece.rotate(rotations[index] * t, Image.Resampling.NEAREST, expand=True)
            # Keep every chip fully inside its own atlas frame.
            left = max(1, min(SIZE - piece.width - 1, round(x - piece.width / 2)))
            top = max(1, min(SIZE - piece.height - 2, round(y - piece.height / 2)))
            image.alpha_composite(piece, (left, top))
        draw = ImageDraw.Draw(image)
        for index, (x, y) in enumerate([(3, 36), (12, 46), (25, 46), (45, 43), (43, 32)]):
            py = round(y - sin(t * pi) * (7 + index))
            draw.rectangle((x, py, x + 1, py + 1), fill=(117, 103, 96, 255))
            draw.point((x, py), fill=(163, 149, 138, 255))
        frames.append(image)
    return frames


def lava_texture():
    # Crop away soil, retaining the source's red cells and yellow molten seams.
    source = Image.open(BLOCKS / "Lava1.jpg").convert("RGB").crop((8, 7, 43, 44))
    return ImageOps.posterize(source.resize((SIZE, SIZE), Image.Resampling.NEAREST), 6).convert("RGBA")


def lava_pool(texture, width, height, top):
    left = (SIZE - width) // 2
    right = left + width
    bottom = min(47, top + height)
    points = [(left, top + height // 2), (left + 3, top + 2),
              (left + width // 4, top + 1), (left + width // 2, top),
              (right - 7, top + 1), (right - 2, top + 3),
              (right, top + height // 2), (right - 2, bottom - 2),
              (right - 10, bottom), (left + 8, bottom), (left + 2, bottom - 2)]
    image = texture_shape(texture, points, LAVA_EDGE)
    draw = ImageDraw.Draw(image)
    draw.line([(left + 4, bottom - 2), (left + 12, bottom - 1),
               (right - 10, bottom - 1), (right - 3, bottom - 3)], fill=(167, 39, 12, 255))
    return image


def lava_frames():
    texture = lava_texture()
    source = Image.open(BLOCKS / "Lava1.jpg").convert("RGBA")
    silhouette = [(12, 5), (19, 8), (26, 4), (32, 8), (39, 7), (44, 17),
                  (42, 25), (46, 32), (40, 41), (32, 45), (23, 42),
                  (14, 45), (7, 36), (5, 26), (9, 18), (8, 12)]
    frames = [texture_shape(source, silhouette, LAVA_EDGE)]
    frames.append(lava_pool(texture, 40, 23, 23))
    # Each crown is an enclosed, irregular fluid sheet, not isolated orange sparks.
    crowns = [
        [(4, 34), (4, 23), (7, 19), (10, 28), (15, 30), (15, 16),
         (18, 13), (22, 27), (26, 29), (30, 16), (34, 13), (34, 27),
         (39, 29), (43, 19), (46, 22), (45, 37), (37, 43), (12, 44)],
        [(3, 36), (5, 29), (9, 25), (13, 34), (18, 35), (20, 25),
         (23, 22), (26, 34), (31, 33), (36, 24), (39, 25), (40, 34),
         (45, 29), (47, 35), (41, 43), (10, 45)],
        [(4, 38), (8, 32), (13, 37), (18, 35), (22, 29), (26, 36),
         (33, 36), (38, 31), (42, 36), (46, 37), (43, 44), (9, 46)],
    ]
    droplets = [
        [(5, 13, 2), (17, 5, 2), (35, 5, 2), (44, 12, 2)],
        [(3, 18, 2), (13, 9, 2), (28, 8, 2), (43, 16, 2), (35, 12, 1)],
        [(4, 29, 1), (12, 22, 2), (28, 20, 1), (44, 27, 2)],
    ]
    for crown, drops in zip(crowns, droplets):
        image = lava_pool(texture, 44, 10, 36)
        image.alpha_composite(texture_shape(texture, crown, LAVA_EDGE))
        draw = ImageDraw.Draw(image)
        for x, y, radius in drops:
            draw.polygon([(x, y - radius), (x + radius, y), (x + radius, y + radius),
                          (x - radius, y + radius), (x - radius, y)], fill=(230, 66, 9, 255))
            draw.point((x, y), fill=(255, 213, 39, 255))
        # Small hot crests echo the native tile's yellow seams.
        for x, y in crown[1:-3:4]:
            draw.line((x, y + 1, x + 1, y + 3), fill=(255, 195, 24, 255), width=1)
        frames.append(image)
    for frame, (width, height, top) in enumerate([(44, 12, 34), (42, 11, 35), (42, 10, 36)]):
        image = lava_pool(texture, width, height, top)
        draw = ImageDraw.Draw(image)
        # A dark cooling skin frames bright liquid, keeping the held residue legible.
        draw.line([(7, 41), (12, 39), (18, 40), (22, 37)], fill=(255, 165, 16, 255), width=2)
        draw.line([(23, 43), (29, 41), (33, 42), (39, 39)], fill=(255, 199, 31, 255), width=1)
        draw.line([(13, 44), (17, 43), (20, 44)], fill=(102, 30, 20, 255), width=2)
        for x, y in [(3, 43), (45, 44), (8, 47), (39, 47)]:
            draw.rectangle((x, y, x + 1, y + 1), fill=(199, 50, 10, 255))
        if frame == 0:
            draw.rectangle((7, 30, 8, 32), fill=(255, 142, 12, 255))
            draw.rectangle((41, 31, 42, 33), fill=(255, 142, 12, 255))
        frames.append(image)
    return frames


def save_sheet(name, frames):
    sheet = Image.new("RGBA", (SIZE * FRAMES, SIZE))
    for index, frame in enumerate(frames):
        sheet.alpha_composite(frame, (index * SIZE, 0))
    path = OUTPUT / name
    sheet.save(path, optimize=True)
    print(f"{path.relative_to(ROOT)}: {sheet.width}x{sheet.height}, {len(frames)} frames")


if __name__ == "__main__":
    save_sheet("rock_breaking.png", rock_frames())
    save_sheet("lava_splash.png", lava_frames())
