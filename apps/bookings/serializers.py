from rest_framework import serializers

from apps.catalog.models import ServiceCategory
from apps.catalog.serializers import SubcategorySerializer
from apps.core.geo import make_point
from apps.fundis.models import FundiProfile

from .models import Booking, Review


class BookingCreateSerializer(serializers.Serializer):
    fundi_id = serializers.PrimaryKeyRelatedField(source="fundi", queryset=FundiProfile.objects.all())
    category = serializers.SlugRelatedField(
        slug_field="slug", queryset=ServiceCategory.objects.filter(is_active=True)
    )
    description = serializers.CharField(max_length=2000)
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    job_address = serializers.CharField(max_length=255)
    landmark = serializers.CharField(max_length=255, required=False, allow_blank=True)
    requested_for = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs["job_location"] = make_point(attrs.pop("latitude"), attrs.pop("longitude"))
        return attrs


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["id", "rating", "comment", "created_at"]
        read_only_fields = ["id", "created_at"]


class PublicReviewSerializer(serializers.ModelSerializer):
    reviewer = serializers.SerializerMethodField()
    category = serializers.CharField(source="booking.category.slug", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "rating", "comment", "reviewer", "category", "created_at"]
        read_only_fields = fields

    def get_reviewer(self, obj) -> str:
        name = (obj.client.full_name or "").strip()
        return name.split()[0] if name else "Client"


class BookingSerializer(serializers.ModelSerializer):
    """Contact details and exact coordinates are only shown to the other party
    once the fundi has accepted."""

    category = SubcategorySerializer(read_only=True)
    fundi = serializers.SerializerMethodField()
    client = serializers.SerializerMethodField()
    job_location = serializers.SerializerMethodField()
    my_role = serializers.SerializerMethodField()
    review = ReviewSerializer(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "reference",
            "status",
            "my_role",
            "category",
            "fundi",
            "client",
            "description",
            "job_address",
            "landmark",
            "job_location",
            "requested_for",
            "expires_at",
            "responded_at",
            "started_at",
            "completed_at",
            "closed_at",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "quoted_price_tzs",
            "final_price_tzs",
            "payment_method",
            "payment_status",
            "review",
            "created_at",
        ]
        read_only_fields = fields

    def _viewer(self):
        return self.context["request"].user

    def _contact_visible(self, obj) -> bool:
        return obj.status in Booking.CONTACT_VISIBLE_STATUSES

    def get_my_role(self, obj):
        return "client" if obj.client_id == self._viewer().pk else "fundi"

    def get_fundi(self, obj):
        data = {"id": str(obj.fundi_id), "business_name": obj.fundi.business_name}
        if self._contact_visible(obj):
            data["phone_number"] = obj.fundi.user.phone_number
        return data

    def get_client(self, obj):
        data = {"id": str(obj.client_id), "full_name": obj.client.full_name}
        if self._contact_visible(obj):
            data["phone_number"] = obj.client.phone_number
        return data

    def get_job_location(self, obj):
        if obj.client_id != self._viewer().pk and not self._contact_visible(obj):
            return None
        return {"latitude": obj.job_location.y, "longitude": obj.job_location.x}


class ActionSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    quoted_price_tzs = serializers.IntegerField(min_value=0, required=False)
    final_price_tzs = serializers.IntegerField(min_value=0, required=False)
