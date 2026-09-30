from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Exists, ExpressionWrapper, F, FloatField, Min, OuterRef, Q, Subquery, Value

from apps.core.images import make_thumbnail
from apps.core.models import BaseModel

# Bayesian rating: every fundi starts as if they had PRIOR_WEIGHT reviews of PRIOR_MEAN stars,
# so one lucky 5-star review can't outrank forty genuine 4.8s.
PRIOR_MEAN = 4.0
PRIOR_WEIGHT = 5


class FundiProfileQuerySet(models.QuerySet):
    def bookable(self):
        """Fundis clients may book: identity verified, profile active, account active."""
        return self.filter(
            status=FundiProfile.Status.ACTIVE,
            user__is_active=True,
            user__identity_status="verified",
            base_location__isnull=False,
        )

    def discoverable(self):
        """Fundis shown in search: bookable and switched on as available."""
        return self.bookable().filter(is_available=True)

    def serving_point(self, point, radius_km=None):
        """Fundis whose service area covers `point`, annotated with `distance` (metres).

        If `radius_km` is given, it also caps the distance (the client's search radius).
        """
        qs = self
        if radius_km is not None:
            qs = qs.filter(base_location__dwithin=(point, D(km=radius_km)))
        return qs.annotate(distance=Distance("base_location", point)).filter(
            distance__lte=F("service_radius_km") * 1000
        )

    def with_score(self):
        """Annotate `score`: the fair ranking used for "top rated"."""
        return self.annotate(
            score=ExpressionWrapper(
                (F("rating_avg") * F("rating_count") + Value(PRIOR_MEAN * PRIOR_WEIGHT))
                / (F("rating_count") + Value(PRIOR_WEIGHT)),
                output_field=FloatField(),
            )
        )

    def with_min_price(self):
        """Annotate `min_price`: the lowest active "from" price in TZS (null if all on quote)."""
        cheapest = (
            FundiService.objects.filter(fundi=OuterRef("pk"), is_active=True, starting_price_tzs__isnull=False)
            .values("fundi")
            .annotate(p=Min("starting_price_tzs"))
            .values("p")
        )
        return self.annotate(min_price=Subquery(cheapest))

    def offering(self, category):
        """Fundis with an active service in `category` or in one of its subcategories."""
        services = FundiService.objects.filter(
            fundi=OuterRef("pk"), is_active=True, category__is_active=True
        ).filter(Q(category=category) | Q(category__parent=category))
        return self.filter(Exists(services))


class FundiProfile(BaseModel):
    """The optional provider side of a user account."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused by fundi"
        SUSPENDED = "suspended", "Suspended"
        BANNED = "banned", "Banned"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="fundi_profile"
    )
    business_name = models.CharField(max_length=120)
    bio = models.TextField(blank=True)
    years_experience = models.PositiveSmallIntegerField(default=0)
    cover_photo = models.ImageField(upload_to="fundis/covers/", blank=True)

    # Where the fundi works from. Never exposed to clients; they only see distance.
    base_location = models.PointField(geography=True, srid=4326, null=True, blank=True)
    service_radius_km = models.PositiveSmallIntegerField(
        default=10, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    area_text = models.CharField(max_length=200, blank=True, help_text="e.g. 'Sinza, near Mori'")
    ward = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)

    is_available = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    status_reason = models.TextField(blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    completed_jobs_count = models.PositiveIntegerField(default=0)
    profile_views = models.PositiveIntegerField(default=0)
    # Average minutes between a job request and the fundi's answer (last 20 answers).
    avg_response_minutes = models.PositiveIntegerField(null=True, blank=True)

    objects = FundiProfileQuerySet.as_manager()

    def __str__(self):
        return self.business_name

    @property
    def is_verified(self) -> bool:
        return self.user.identity_status == "verified"


class FundiService(BaseModel):
    """A category a fundi offers, with per-category experience and pricing."""

    class PricingType(models.TextChoices):
        FIXED = "fixed", "Fixed price"
        HOURLY = "hourly", "Per hour"
        CALLOUT = "callout", "Call-out fee"
        QUOTE = "quote", "Quote on site"

    fundi = models.ForeignKey(FundiProfile, on_delete=models.CASCADE, related_name="services")
    category = models.ForeignKey(
        "catalog.ServiceCategory", on_delete=models.PROTECT, related_name="fundi_services"
    )
    is_primary = models.BooleanField(default=False)
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    pricing_type = models.CharField(
        max_length=20, choices=PricingType.choices, default=PricingType.QUOTE
    )
    starting_price_tzs = models.PositiveIntegerField(null=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["fundi", "category"], name="unique_fundi_category"),
            models.UniqueConstraint(
                fields=["fundi"], condition=Q(is_primary=True), name="one_primary_service_per_fundi"
            ),
        ]

    def __str__(self):
        return f"{self.fundi} – {self.category}"


class WorkPhoto(BaseModel):
    """A photo of a job the fundi has done — the portfolio clients browse."""

    MAX_PER_FUNDI = 12

    fundi = models.ForeignKey(FundiProfile, on_delete=models.CASCADE, related_name="work_photos")
    image = models.ImageField(upload_to="fundis/work/")
    thumbnail = models.ImageField(upload_to="fundis/work/thumbs/", blank=True, editable=False)
    caption = models.CharField(max_length=140, blank=True)
    category = models.ForeignKey(
        "catalog.ServiceCategory", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "-created_at"]

    def __str__(self):
        return f"{self.fundi} – {self.caption or self.image.name}"

    def save(self, *args, **kwargs):
        # Small thumbnails keep lists fast and cheap on mobile data.
        if self.image and not self.thumbnail:
            self.thumbnail = make_thumbnail(self.image, max_size=480)
        super().save(*args, **kwargs)


class FavoriteFundi(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_fundis")
    fundi = models.ForeignKey(FundiProfile, on_delete=models.CASCADE, related_name="favorited_by")

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "fundi"], name="unique_favorite_fundi")]
