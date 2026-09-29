from django.conf import settings
from rest_framework import serializers

from apps.catalog.models import ServiceCategory
from apps.catalog.serializers import SubcategorySerializer
from apps.core.geo import make_point

from .models import FundiProfile, FundiService


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


class PublicFundiSerializer(serializers.ModelSerializer):
    """What clients see. No coordinates and no phone number before a booking is accepted."""

    is_verified = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = FundiProfile
        fields = [
            "id",
            "business_name",
            "bio",
            "years_experience",
            "photo",
            "area_text",
            "district",
            "region",
            "is_available",
            "is_verified",
            "rating_avg",
            "rating_count",
            "completed_jobs_count",
            "services",
            "distance_km",
        ]

    def get_is_verified(self, obj) -> bool:
        return obj.is_verified

    def get_services(self, obj):
        active = [s for s in obj.services.all() if s.is_active and s.category.is_active]
        return FundiServiceSerializer(active, many=True).data

    def get_distance_km(self, obj):
        distance = getattr(obj, "distance", None)
        return round(distance.km, 1) if distance is not None else None


class FundiSearchSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    radius_km = serializers.FloatField(
        min_value=0.5, max_value=settings.SEARCH_MAX_RADIUS_KM, required=False
    )
    category = serializers.SlugRelatedField(
        slug_field="slug", queryset=ServiceCategory.objects.filter(is_active=True), required=False
    )
