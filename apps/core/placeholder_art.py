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


# Palette per person (portrait background, clothing).
PEOPLE = [
    ((231, 214, 196), (7, 114, 70)),
    ((214, 226, 240), (30, 58, 138)),
    ((240, 224, 206), (120, 53, 15)),
    ((222, 234, 226), (15, 118, 110)),
    ((236, 222, 240), (76, 29, 149)),
    ((242, 230, 210), (180, 83, 9)),
]
SKIN = [(141, 85, 36), (120, 72, 33), (98, 58, 28), (160, 102, 56), (111, 66, 34)]

CARD_STYLES = {
    # (header colour, header text, background)
    "nida": ((22, 101, 52), "JAMHURI YA MUUNGANO WA TANZANIA · NIDA", (236, 244, 238)),
    "driving_licence": ((30, 64, 175), "TANZANIA DRIVING LICENCE", (234, 240, 250)),
    "passport": ((30, 41, 59), "UNITED REPUBLIC OF TANZANIA · PASSPORT", (244, 241, 234)),
}


def _draw_person(size: int, seed: int) -> Image.Image:
    """A simple illustrated head-and-shoulders portrait (no real person)."""
    rng = random.Random(seed)
    bg, shirt = PEOPLE[rng.randrange(len(PEOPLE))]
    skin = SKIN[rng.randrange(len(SKIN))]
    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    s = size
    d.ellipse((s * 0.14, s * 0.70, s * 0.86, s * 1.35), fill=shirt)  # shoulders
    d.rectangle((s * 0.43, s * 0.58, s * 0.57, s * 0.76), fill=skin)  # neck
    d.ellipse((s * 0.30, s * 0.20, s * 0.70, s * 0.66), fill=skin)  # head
    hair = (25, 20, 18)
    if rng.random() < 0.5:
        d.chord((s * 0.29, s * 0.17, s * 0.71, s * 0.52), 180, 360, fill=hair)  # short hair
    else:
        d.ellipse((s * 0.26, s * 0.12, s * 0.74, s * 0.40), fill=hair)  # headwrap / hair
    eye = (30, 25, 22)
    for ex in (0.42, 0.58):
        d.ellipse((s * (ex - 0.025), s * 0.40, s * (ex + 0.025), s * 0.45), fill=eye)
    d.arc((s * 0.43, s * 0.46, s * 0.57, s * 0.56), 20, 160, fill=(90, 40, 30), width=max(2, s // 90))
    return img


def id_card(document_type: str, full_name: str, number: str, seed: int, size=(1000, 630)) -> bytes:
    """A mock ID document with the holder's photo where the real document prints it.
    The photo box matches `apps.verification.portrait.TEMPLATES`, so the portrait crop finds it."""
    from apps.verification.portrait import TEMPLATES

    header, title, background = CARD_STYLES.get(document_type, CARD_STYLES["nida"])
    w, h = size
    card = Image.new("RGB", size, background)
    d = ImageDraw.Draw(card)
    font = ImageFont.load_default(size=26)
    small = ImageFont.load_default(size=22)
    if document_type == "passport":
        d.rectangle((0, 0, w, int(h * 0.46)), fill=(214, 206, 190))  # visa page half
        d.text((40, 40), title, fill=header, font=font)
    else:
        d.rectangle((0, 0, w, int(h * 0.17)), fill=header)
        d.text((40, int(h * 0.06)), title, fill="white", font=font)

    left, top, bw, bh = TEMPLATES.get(document_type, TEMPLATES["nida"])
    box = (int(left * w), int(top * h), int((left + bw) * w), int((top + bh) * h))
    bw_px, bh_px = box[2] - box[0], box[3] - box[1]
    side = min(bw_px, bh_px)
    person = _draw_person(side, seed)
    # Fill the whole photo box, like a real ID photo, with the person at the bottom.
    photo = Image.new("RGB", (bw_px, bh_px), person.getpixel((2, 2)))
    photo.paste(person, ((bw_px - side) // 2, bh_px - side))
    card.paste(photo, box[:2])

    x = box[2] + 40
    y = box[1] + 10
    for label, value in (("Jina / Name", full_name), ("Namba / Number", number), ("Uraia", "Mtanzania")):
        d.text((x, y), label, fill=(90, 100, 95), font=small)
        d.text((x, y + 28), value, fill=(20, 26, 22), font=font)
        y += 90
    out = io.BytesIO()
    card.save(out, format="JPEG", quality=85)
    return out.getvalue()
