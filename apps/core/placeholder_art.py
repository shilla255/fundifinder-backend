"""Offline placeholder "work photos" for demo data (gradient art with a trade icon).

Used by `seed_demo` when real stock photos can't be downloaded.
"""

import io
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ICON_FONT = Path(__file__).parent / "assets" / "MaterialIcons-Regular.ttf"

# Material Icons codepoints per category slug.
ICONS = {
    "electrical": "",
    "electrical-wiring": "",
    "solar-installation": "",
    "plumbing": "",
    "mechanics": "",
    "motorcycle-mechanics": "",
    "carpentry": "",
    "masonry": "",
    "painting": "",
    "welding": "",
    "ac-refrigeration": "",
    "electronics-repair": "",
}
DEFAULT_ICON = ""  # handyman

# (dark, light) gradient pairs in the FundiFinder palette family.
PALETTES = [
    ((3, 42, 27), (18, 176, 104)),
    ((10, 74, 49), (52, 204, 130)),
    ((120, 53, 15), (245, 158, 11)),
    ((30, 58, 138), (96, 165, 250)),
    ((76, 29, 149), (167, 139, 250)),
    ((15, 118, 110), (94, 234, 212)),
]


def work_photo(category_slug: str, seed: int, size=(1200, 900)) -> bytes:
    """A 4:3 JPEG with a diagonal gradient, soft light and a large trade icon."""
    rng = random.Random(seed)
    w, h = size
    dark, light = PALETTES[rng.randrange(len(PALETTES))]

    # Diagonal gradient.
    base = Image.new("RGB", size)
    px = base.load()
    angle = rng.uniform(0.3, 1.2)
    ca, sa = math.cos(angle), math.sin(angle)
    span = w * ca + h * sa
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            t = (x * ca + y * sa) / span
            c = tuple(int(dark[i] + (light[i] - dark[i]) * t) for i in range(3))
            px[x, y] = c
            if x + 1 < w:
                px[x + 1, y] = c
            if y + 1 < h:
                px[x, y + 1] = c
                if x + 1 < w:
                    px[x + 1, y + 1] = c

    # Soft light blobs.
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(4):
        r = rng.randint(int(h * 0.25), int(h * 0.6))
        cx, cy = rng.randint(0, w), rng.randint(0, h)
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, rng.randint(18, 40)))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(base.convert("RGBA"), glow)

    # Faint icon pattern + one large icon with a soft shadow.
    icon = ICONS.get(category_slug, DEFAULT_ICON)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    small = ImageFont.truetype(str(ICON_FONT), 64)
    for gy in range(-40, h, 150):
        for gx in range(-40 + (gy // 150 % 2) * 75, w, 150):
            ld.text((gx, gy), icon, font=small, fill=(255, 255, 255, 18))
    big = ImageFont.truetype(str(ICON_FONT), int(h * 0.55))
    bx, by = int(w * rng.uniform(0.28, 0.42)), int(h * 0.2)
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text((bx + 18, by + 24), icon, font=big, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    img = Image.alpha_composite(img, layer)
    img = Image.alpha_composite(img, shadow)
    ImageDraw.Draw(img).text((bx, by), icon, font=big, fill=(255, 255, 255, 235))

    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=84, optimize=True, progressive=True)
    return out.getvalue()
