from django.conf import settings
from django.db.models import Count
from rest_framework import serializers

from apps.catalog.models import ServiceCategory
from apps.catalog.serializers import SubcategorySerializer
from apps.core.geo import make_point

from .models import FundiProfile, FundiService, WorkPhoto


class FundiServiceSerializer(serializers.ModelSerializer):
    category = SubcategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=ServiceCategory.objects.filter(is_active=True),
        write_only=True,
    )

    class Meta:
        model = FundiService
        fields = [
            "id",
            "category",
            "category_id",
            "is_primary",
            "years_experience",
            "pricing_type",
            "starting_price_tzs",
            "description",
            "is_active",
        ]

    def validate(self, attrs):
        fundi = self.context["fundi"]
        category = attrs.get("category")
        others = fundi.services.exclude(pk=getattr(self.instance, "pk", None))
        if category and others.filter(category=category).exists():
            raise serializers.ValidationError({"category_id": "You already offer this service."})
        if self.instance is None and others.count() >= settings.FUNDI_MAX_SERVICES:
            raise serializers.ValidationError(
                f"You can offer at most {settings.FUNDI_MAX_SERVICES} services."
            )
        if attrs.get("is_primary") and others.filter(is_primary=True).exists():
            raise serializers.ValidationError(
                {"is_primary": "Another service is already marked as primary."}
            )
        return attrs


class FundiProfileSerializer(serializers.ModelSerializer):
    """The fundi's own view of their profile, including their exact location."""

    latitude = serializers.FloatField(
        min_value=-90, max_value=90, required=False, write_only=True
    )
    longitude = serializers.FloatField(
        min_value=-180, max_value=180, required=False, write_only=True
    )
    location = serializers.SerializerMethodField()
    services = FundiServiceSerializer(many=True, read_only=True)
    identity_status = serializers.CharField(source="user.identity_status", read_only=True)
    is_discoverable = serializers.SerializerMethodField()

    class Meta:
        model = FundiProfile
        fields = [
            "id",
            "business_name",
            "bio",
            "years_experience",
            "photo",
            "latitude",
            "longitude",
            "location",
            "service_radius_km",
            "area_text",
            "ward",
            "district",
            "region",
            "is_available",
            "status",
            "status_reason",
            "identity_status",
            "is_discoverable",
            "rating_avg",
            "rating_count",
            "completed_jobs_count",
            "services",
            "created_at",
        ]
        read_only_fields = [
            "status",
            "status_reason",
            "rating_avg",
            "rating_count",
            "completed_jobs_count",
            "created_at",
        ]

    def get_location(self, obj):
        if obj.base_location is None:
            return None
        return {"latitude": obj.base_location.y, "longitude": obj.base_location.x}

    def get_is_discoverable(self, obj) -> bool:
        return FundiProfile.objects.discoverable().filter(pk=obj.pk).exists()

    def validate(self, attrs):
        lat, lng = attrs.pop("latitude", None), attrs.pop("longitude", None)
        if (lat is None) != (lng is None):
            raise serializers.ValidationError("Send latitude and longitude together.")
        if lat is not None:
            attrs["base_location"] = make_point(lat, lng)
        return attrs


class WorkPhotoSerializer(serializers.ModelSerializer):
    category = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = WorkPhoto
        fields = ["id", "image", "thumbnail", "caption", "category", "created_at"]
        read_only_fields = fields


def badges_for(fundi) -> list[str]:
    """Trust badges shown on cards and profiles."""
    badges = []
    if fundi.is_verified:
        badges.append("verified")
    score = getattr(fundi, "score", None)
    if fundi.rating_count >= 3 and (score if score is not None else float(fundi.rating_avg)) >= 4.3:
        badges.append("top_rated")
    if fundi.avg_response_minutes is not None and fundi.avg_response_minutes <= 30:
        badges.append("quick_responder")
    if fundi.years_experience >= 5:
        badges.append("experienced")
    return badges


class PublicFundiSerializer(serializers.ModelSerializer):
    """What clients see in lists. No coordinates and no phone number before a booking is accepted."""

    is_verified = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()
    approx_location = serializers.SerializerMethodField()
    cover_image = serializers.SerializerMethodField()
    badges = serializers.SerializerMethodField()
    min_price_tzs = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()
    member_since = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = FundiProfile
        fields = [
            "id",
            "business_name",
            "bio",
            "years_experience",
            "photo",
            "cover_image",
            "area_text",
            "district",
            "region",
            "is_available",
            "is_verified",
            "badges",
            "rating_avg",
            "rating_count",
            "completed_jobs_count",
            "avg_response_minutes",
            "min_price_tzs",
            "services",
            "distance_km",
            "approx_location",
            "is_favorite",
            "member_since",
        ]

    def _url(self, field):
        if not field:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(field.url) if request else field.url

    def get_is_verified(self, obj) -> bool:
        return obj.is_verified

    def get_services(self, obj):
        active = [s for s in obj.services.all() if s.is_active and s.category.is_active]
        return FundiServiceSerializer(active, many=True).data

    def get_cover_image(self, obj):
        """The fundi's cover photo, or their first work photo as a fallback."""
        if obj.cover_photo:
            return self._url(obj.cover_photo)
        photos = list(obj.work_photos.all()[:1])
        return self._url(photos[0].thumbnail or photos[0].image) if photos else None

    def get_badges(self, obj):
        return badges_for(obj)

    def get_min_price_tzs(self, obj):
        if hasattr(obj, "min_price"):
            return obj.min_price
        prices = [s.starting_price_tzs for s in obj.services.all() if s.is_active and s.starting_price_tzs]
        return min(prices) if prices else None

    def get_is_favorite(self, obj) -> bool:
        return obj.pk in self.context.get("favorite_ids", ())

    def get_approx_location(self, obj):
        """Rounded to 2 decimals (~1 km) so maps can show the area, not the fundi's home."""
        if obj.base_location is None:
            return None
        return {"latitude": round(obj.base_location.y, 2), "longitude": round(obj.base_location.x, 2)}

    def get_distance_km(self, obj):
        distance = getattr(obj, "distance", None)
        return round(distance.km, 1) if distance is not None else None


class PublicFundiDetailSerializer(PublicFundiSerializer):
    """The full public profile: portfolio and a breakdown of star ratings."""

    work_photos = WorkPhotoSerializer(many=True, read_only=True)
    rating_breakdown = serializers.SerializerMethodField()

    class Meta(PublicFundiSerializer.Meta):
        fields = [*PublicFundiSerializer.Meta.fields, "work_photos", "rating_breakdown"]

    def get_rating_breakdown(self, obj):
        from apps.bookings.models import Review

        counts = dict(Review.objects.filter(fundi=obj).values_list("rating").annotate(n=Count("id")))
        return {str(stars): counts.get(stars, 0) for stars in range(5, 0, -1)}


class FundiSearchSerializer(serializers.Serializer):
    SORTS = ("distance", "rating", "jobs", "price")

    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    radius_km = serializers.FloatField(
        min_value=0.5, max_value=settings.SEARCH_MAX_RADIUS_KM, required=False
    )
    category = serializers.SlugRelatedField(
        slug_field="slug", queryset=ServiceCategory.objects.filter(is_active=True), required=False
    )
    min_rating = serializers.FloatField(min_value=0, max_value=5, required=False)
    max_price = serializers.IntegerField(min_value=0, required=False)
    available_now = serializers.BooleanField(required=False, default=False)
    sort = serializers.ChoiceField(choices=SORTS, required=False, default="distance")
    q = serializers.CharField(max_length=60, required=False, allow_blank=True, trim_whitespace=True)


class TopFundisSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lng = serializers.FloatField(min_value=-180, max_value=180, required=False)
    radius_km = serializers.FloatField(min_value=1, max_value=200, required=False, default=30)
    category = serializers.SlugRelatedField(
        slug_field="slug", queryset=ServiceCategory.objects.filter(is_active=True), required=False
    )
    limit = serializers.IntegerField(min_value=1, max_value=30, required=False, default=10)
