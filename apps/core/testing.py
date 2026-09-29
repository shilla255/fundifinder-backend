"""Small helpers for building test data."""

import io
import itertools

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import User
from apps.catalog.models import ServiceCategory
from apps.core.geo import make_point
from apps.fundis.models import FundiProfile, FundiService

_seq = itertools.count(1)

# Two points in Dar es Salaam about 3.3 km apart (Sinza and Mwenge).
SINZA = (-6.7836, 39.2208)
MWENGE = (-6.7711, 39.2489)
# About 30 km away, in Bagamoyo road direction.
FAR_AWAY = (-6.5200, 39.1100)


def make_user(**kwargs) -> User:
    n = next(_seq)
    kwargs.setdefault("email", f"user{n}@example.com")
    kwargs.setdefault("full_name", f"User {n}")
    kwargs.setdefault("phone_number", f"+2557120000{n:02d}")
    return User.objects.create_user(**kwargs)


def make_category(slug="electrical", parent=None) -> ServiceCategory:
    category, _ = ServiceCategory.objects.get_or_create(
        slug=slug, defaults={"name_en": slug.title(), "name_sw": f"Huduma ya {slug}", "parent": parent}
    )
    return category


def make_fundi(
    user=None, *, location=SINZA, category=None, verified=True, active=True, radius_km=10, **kwargs
) -> FundiProfile:
    user = user or make_user()
    if verified:
        user.identity_status = User.IdentityStatus.VERIFIED
        user.save(update_fields=["identity_status"])
    profile = FundiProfile.objects.create(
        user=user,
        business_name=kwargs.pop("business_name", f"Fundi {user.full_name}"),
        base_location=make_point(*location) if location else None,
        service_radius_km=radius_km,
        status=FundiProfile.Status.ACTIVE if active else FundiProfile.Status.DRAFT,
        **kwargs,
    )
    FundiService.objects.create(fundi=profile, category=category or make_category(), is_primary=True)
    return profile


def image_file(name="photo.jpg") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")
