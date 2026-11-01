#!/usr/bin/env python3
"""Rebuild the native-density Sinclair sprite with Pillow (python -m pip install Pillow).

Run from any directory: python verification/generate_sinclair_station.py
Sources remain unchanged. The output is 150x150 RGBA, 50 px/world tile;
place its top-left at Godot (3, 1), replacing Shop125-130 at cells (3..5, 3..4).
The added overhead sign's blank face is (29, 6, 94, 22), with safe text bounds
(33, 8, 86, 16), expressed as x, y, width, height in output pixels.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
BLOCKS = ROOT / "godot/assets/Resources/Blocks"
OUTPUT = ROOT / "godot/assets/sinclair_station.png"
PRICE_FACE = (29, 6, 94, 22)
PRICE_TEXT = (33, 8, 86, 16)


def shop_grid(first, columns, rows):
    image = Image.new("RGBA", (columns * 50, rows * 50))
    for index in range(columns * rows):
        tile = Image.open(BLOCKS / f"Shop{first + index}.png").convert("RGBA")
        image.alpha_composite(tile, (index % columns * 50, index // columns * 50))
    return image


def material(image, box, color, texture, strength=0.35):
    """Tint original shop masonry grain, without introducing higher-res noise."""
    left, top, right, bottom = box
    for y in range(top, bottom):
        for x in range(left, right):
            source = texture.getpixel((75 + x % 20, 88 + y % 20))
            luminance = (source[0] + source[1] + source[2]) / 3
            shade = 1 + (luminance - 105) / 105 * strength
            image.putpixel((x, y), tuple(max(0, min(255, int(c * shade))) for c in color) + (255,))


def label(image, text, box, size, color):
    font = ImageFont.truetype(str(ROOT / "godot/assets/MyFonts/214_Arial Black.ttf"), size)
    mask = Image.new("L", (150, 30))
    draw = ImageDraw.Draw(mask)
    bounds = draw.textbbox((0, 0), text, font=font)
    draw.text((-bounds[0], -bounds[1]), text, font=font, fill=255)
    mask = mask.crop((0, 0, bounds[2] - bounds[0], bounds[3] - bounds[1]))
    width = min(mask.width, box[2] - box[0])
    height = min(mask.height, box[3] - box[1])
    if mask.size != (width, height):
        mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    x = box[0] + (box[2] - box[0] - width) // 2
    y = box[1] + (box[3] - box[1] - height) // 2
    image.paste(color, (x, y), mask)


def small_label(image, text, x, y, color):
    # Explicit 3x5 raster lettering stays readable under nearest filtering.
    glyphs = {
        "A": ("010", "101", "111", "101", "101"),
        "D": ("110", "101", "101", "101", "110"),
        "E": ("111", "100", "110", "100", "111"),
        "G": ("111", "100", "101", "101", "111"),
        "L": ("100", "100", "100", "100", "111"),
        "N": ("101", "111", "111", "111", "101"),
        "O": ("010", "101", "101", "101", "010"),
        "P": ("110", "101", "110", "100", "100"),
        "R": ("110", "101", "110", "101", "101"),
        "S": ("111", "100", "111", "001", "111"),
        "T": ("111", "010", "010", "010", "010"),
        "U": ("101", "101", "101", "101", "111"),
        "/": ("001", "001", "010", "100", "100"),
        " ": ("000", "000", "000", "000", "000"),
    }
    draw = ImageDraw.Draw(image)
    for index, character in enumerate(text):
        for row, pixels in enumerate(glyphs[character]):
            for column, pixel in enumerate(pixels):
                if pixel == "1":
                    draw.point((x + index * 4 + column, y + row), fill=color)


def dinosaur(image):
    """Custom long-neck Sinclair-style dinosaur silhouette at native raster density."""
    draw = ImageDraw.Draw(image)
    draw.ellipse((62, 99, 103, 129), fill=(111, 124, 109), outline=(35, 62, 44))
    draw.ellipse((63, 100, 102, 127), fill=(220, 224, 201), outline=(232, 231, 207))
    green = (21, 112, 53)
    # Rounded back, raised neck/head, sweeping tail, and four separated feet.
    draw.polygon([(67, 118), (72, 115), (75, 111), (81, 110), (88, 112),
                  (90, 111), (91, 105), (93, 103), (98, 103), (99, 105),
                  (98, 107), (95, 107), (95, 114), (93, 118), (91, 119),
                  (91, 124), (88, 124), (87, 119), (84, 119), (84, 124),
                  (81, 124), (80, 119), (77, 118), (75, 121), (72, 122),
                  (72, 120), (69, 119)], fill=green)
    draw.line([(69, 117), (65, 115), (66, 118), (71, 120)], fill=green)
    draw.line([(77, 112), (81, 111), (86, 112)], fill=(54, 136, 64))
    draw.point((97, 104), fill=(226, 231, 203))
    draw.line((71, 126, 95, 126), fill=(147, 51, 38))


def build():
    native = shop_grid(125, 3, 2)
    masonry = shop_grid(110, 4, 3)
    image = Image.new("RGBA", (150, 150))
    draw = ImageDraw.Draw(image)

    # Weathered structural steel supports behind the original pump machinery.
    for x in (46, 107):
        material(image, (x, 26, x + 4, 93), (76, 83, 74), masonry)
        draw.line((x, 27, x, 92), fill=(134, 138, 119))
        draw.line((x + 3, 28, x + 3, 92), fill=(42, 48, 44))

    # Exact native fuel-station footprint, hoses, nozzles and beveled foundation.
    image.alpha_composite(native, (0, 50))
    # Refinish only the central sheet-metal housing; retain source grain/shading.
    for y in range(88, 136):
        for x in range(50, 110):
            r, g, b, alpha = image.getpixel((x, y))
            if alpha and (y < 132 or 53 <= x <= 107):
                value = (r + g + b) / 3
                image.putpixel((x, y), (min(225, int(value * 1.48 + 32)),
                                       min(227, int(value * 1.50 + 34)),
                                       min(213, int(value * 1.41 + 31)), alpha))
    # Green enamel trim follows the existing trapezoidal pump and foundation.
    for y in range(132, 136):
        for x in range(51, 110):
            r, g, b, alpha = image.getpixel((x, y))
            if alpha:
                value = (r + g + b) / 3
                image.putpixel((x, y), (int(value * .18), int(value * .57), int(value * .28), alpha))

    # Original Shop110-121 roof vents transplanted 1:1, not upscaled illustrations.
    vent = masonry.crop((60, 19, 75, 33))
    image.alpha_composite(vent, (13, 77))
    image.alpha_composite(vent, (30, 77))

    # Replace the old red FUEL panel with a framed, distressed Sinclair fascia.
    material(image, (49, 58, 111, 86), (67, 75, 61), masonry)
    material(image, (51, 60, 109, 84), (209, 216, 192), masonry, .16)
    draw.line((50, 59, 109, 59), fill=(167, 178, 150))
    draw.line((50, 59, 50, 84), fill=(162, 173, 145))
    draw.line((50, 85, 110, 85), fill=(34, 47, 37))
    material(image, (53, 62, 107, 74), (18, 106, 47), masonry, .18)
    label(image, "SINCLAIR", (54, 63, 106, 73), 10, (238, 235, 211))
    small_label(image, "PROPELLANT", 60, 77, (43, 72, 47))
    for x, y in ((51, 60), (108, 60), (51, 83), (108, 83)):
        draw.point((x, y), fill=(219, 220, 190))
        draw.point((x + 1, y + 1), fill=(46, 59, 46))

    dinosaur(image)
    # Small native-density seams, access plate and service fasteners.
    draw.line((57, 92, 57, 128), fill=(94, 110, 96))
    draw.line((102, 91, 102, 98), fill=(94, 110, 96))
    draw.rectangle((59, 93, 68, 96), fill=(43, 60, 47), outline=(137, 150, 126))
    for x, y in ((55, 90), (104, 90), (54, 130), (106, 130)):
        draw.point((x, y), fill=(225, 224, 195))
        draw.point((x + 1, y + 1), fill=(76, 91, 77))

    # Overhead sign deliberately has no fabricated numerical price baked in.
    material(image, (26, 3, 126, 31), (78, 91, 75), masonry)
    draw.line((27, 3, 124, 3), fill=(170, 185, 152))
    draw.line((26, 4, 26, 29), fill=(164, 180, 146))
    draw.line((28, 30, 125, 30), fill=(32, 48, 37))
    draw.rectangle((28, 5, 123, 28), fill=(34, 93, 49))
    draw.rectangle((29, 6, 122, 27), fill=(16, 30, 22))
    for x, y in ((27, 4), (124, 4), (27, 29), (124, 29)):
        draw.point((x, y), fill=(207, 212, 176))
    material(image, (49, 32, 103, 41), (58, 69, 55), masonry, .2)
    small_label(image, "USD / US GAL", 52, 34, (205, 215, 182))
    # A handful of enamel chips reference the original stone color underneath.
    for x, y in ((53, 63), (104, 73), (108, 79), (35, 4), (117, 29)):
        draw.point((x, y), fill=(116, 125, 99))

    image.save(OUTPUT, optimize=True)
    return image


if __name__ == "__main__":
    build()
    print(OUTPUT.relative_to(ROOT))
