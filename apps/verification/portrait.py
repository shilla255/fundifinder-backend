"""Where a fundi's photo comes from: their approved ID document, never a custom upload.

Sources are tried in order; the first that returns a photo wins:

1. `NidaApiSource`   — the official photo from NIDA's API (not available yet; returns None).
2. `DocumentCropSource` — the face cut from the uploaded document image:
      a. face detection (OpenCV YuNet, bundled model) → a square around the face;
      b. otherwise the fixed spot where each document type prints the photo.
   Staff can adjust the box in the admin and regenerate.

The result is a square JPEG, stored publicly, used as the person's avatar.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

MODEL = Path(__file__).parent / "assets" / "face_detection_yunet_2023mar.onnx"
OUTPUT_SIZE = 512

# Where the holder's photo sits on the front of each document, as fractions of the image
# (left, top, width, height), for a photo of the card filling the frame.
TEMPLATES = {
    # Tanzanian NIDA card: photo on the left, under the header band.
    "nida": (0.03, 0.24, 0.30, 0.62),
    # Tanzanian driving licence (smart card): photo on the left.
    "driving_licence": (0.03, 0.22, 0.28, 0.60),
    # Passport data page: photo on the left of the lower (data) half.
    "passport": (0.04, 0.50, 0.28, 0.42),
}


@dataclass
class Portrait:
    image: bytes
    method: str  # "nida_api" | "face_detection" | "template"
    box: tuple[float, float, float, float] | None = None


class NidaApiSource:
    """Placeholder for the NIDA identity API, which returns the registered photo.
    Plug the client in here when access is granted; everything downstream stays the same."""

    method = "nida_api"

    def fetch(self, verification) -> Portrait | None:
        return None


class DocumentCropSource:
    method = "document_crop"

    def fetch(self, verification, box=None) -> Portrait | None:
        if not verification.id_front_image:
            return None
        with verification.id_front_image.open("rb") as f:
            image = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
        method = "manual" if box else None
        if box is None:
            try:
                box = detect_face_box(image)
            except Exception:  # noqa: BLE001 — a detector problem falls back to the template
                log.exception("Face detection failed")
                box = None
            method = "face_detection" if box else "template"
        if box is None:
            box = TEMPLATES.get(verification.document_type, TEMPLATES["nida"])
        return Portrait(image=crop_square(image, box), method=method, box=tuple(round(float(v), 4) for v in box))


SOURCES = [NidaApiSource(), DocumentCropSource()]


def extract(verification, box=None) -> Portrait | None:
    """Best available portrait for a verification. `box` forces a manual crop."""
    if box is not None:
        return DocumentCropSource().fetch(verification, box=box)
    for source in SOURCES:
        try:
            portrait = source.fetch(verification)
        except Exception:  # noqa: BLE001 — a failing source must not block approval
            log.exception("Portrait source %s failed", source.method)
            continue
        if portrait:
            return portrait
    return None


def detect_face_box(image: Image.Image) -> tuple[float, float, float, float] | None:
    """Largest confident face, expanded to include hair and chin, as a fractional box.
    Returns None if OpenCV isn't installed or no face is found."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    if not MODEL.exists():
        return None
    try:  # quieten OpenCV's backend warnings
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except AttributeError:
        pass

    # Detect on a downscaled copy: faster, and ID photos are small anyway.
    scale = min(1.0, 1024 / max(image.size))
    small = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    bgr = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2BGR)
    detector = cv2.FaceDetectorYN.create(str(MODEL), "", (small.width, small.height), 0.75)
    _, faces = detector.detect(bgr)
    if faces is None or not len(faces):
        return None
    x, y, w, h = (float(v) for v in max(faces, key=lambda f: f[2] * f[3])[:4])
    # Head-and-shoulders framing: 1.9× the face box, a little above centre.
    side = max(w, h) * 1.9
    cx, cy = x + w / 2, y + h / 2 - h * 0.08
    left, top = cx - side / 2, cy - side / 2
    W, H = small.width, small.height
    return (max(left, 0) / W, max(top, 0) / H, min(side, W) / W, min(side, H) / H)


def crop_square(image: Image.Image, box) -> bytes:
    """Cut `box` (fractions) out of the image, pad to a square and encode as JPEG."""
    left, top, width, height = box
    W, H = image.size
    region = image.crop((
        int(max(0, left) * W),
        int(max(0, top) * H),
        int(min(1, left + width) * W),
        int(min(1, top + height) * H),
    ))
    side = max(region.size)
    square = Image.new("RGB", (side, side), region.getpixel((0, 0)))
    square.paste(region, ((side - region.width) // 2, (side - region.height) // 2))
    square = square.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    square.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()
