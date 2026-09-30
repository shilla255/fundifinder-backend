import io
import uuid
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps


def make_thumbnail(image_field, max_size: int = 480, quality: int = 78) -> ContentFile:
    """JPEG thumbnail (longest side `max_size`) for an uploaded image, EXIF rotation applied."""
    image_field.open()
    with Image.open(image_field) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_size, max_size))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    image_field.seek(0)
    name = f"{Path(image_field.name).stem or uuid.uuid4().hex}_thumb.jpg"
    return ContentFile(buffer.getvalue(), name=name)
