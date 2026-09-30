from django.urls import reverse
from rest_framework import serializers

from apps.accounts.models import User
from apps.bookings.models import Booking, BookingEvent
from apps.fundis.models import FundiProfile
from apps.fundis.serializers import portrait_url
from apps.verification.models import IdentityVerification as IV

from .models import StaffAction


def _abs(request, url):
    return request.build_absolute_uri(url) if request else url


class PersonSerializer(serializers.ModelSerializer):
    """Compact user card used across the console."""

    name = serializers.SerializerMethodField()
    is_fundi = serializers.SerializerMethodField()
    portrait = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "name", "email", "phone_number", "phone_verified", "identity_status", "is_fundi",
            "is_active", "is_staff", "portrait", "date_joined",
        ]

    def get_name(self, obj) -> str:
        return obj.full_name or obj.email or obj.phone_number or "—"

    def get_is_fundi(self, obj) -> bool:
        return hasattr(obj, "fundi_profile")

    def get_portrait(self, obj):
        return portrait_url(obj, self.context.get("request"))


class UserListSerializer(PersonSerializer):
    bookings_count = serializers.IntegerField(read_only=True)
    fundi_id = serializers.SerializerMethodField()

    class Meta(PersonSerializer.Meta):
        fields = [*PersonSerializer.Meta.fields, "preferred_language", "bookings_count", "fundi_id", "last_login"]

    def get_fundi_id(self, obj):
        profile = getattr(obj, "fundi_profile", None)
        return str(profile.pk) if profile else None


class VerificationSerializer(serializers.ModelSerializer):
    user = PersonSerializer(read_only=True)
    document_type_display = serializers.CharField(source="get_document_type_display", read_only=True)
    masked_number = serializers.SerializerMethodField()
    dob_matches_nida = serializers.BooleanField(read_only=True, allow_null=True)
    portrait = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    fundi = serializers.SerializerMethodField()
    reviewed_by = serializers.SerializerMethodField()
    previous_submissions = serializers.SerializerMethodField()

    class Meta:
        model = IV
        fields = [
            "id", "status", "document_type", "document_type_display", "full_name", "date_of_birth",
            "masked_number", "document_last4", "dob_matches_nida", "is_duplicate_document",
            "portrait", "portrait_method", "portrait_box", "images", "user", "fundi",
            "rejection_reason", "review_note", "reviewed_by", "reviewed_at", "created_at", "previous_submissions",
        ]

    def get_masked_number(self, obj) -> str:
        n = obj.document_number
        if obj.document_type == IV.DocumentType.NIDA and len(n) == 20:
            return f"{n[:8]}-•••••-•••••-{n[-2:]}"
        return f"{'•' * max(len(n) - 4, 0)}{obj.document_last4}"

    def get_portrait(self, obj):
        return _abs(self.context.get("request"), obj.portrait.url) if obj.portrait else None

    def get_images(self, obj) -> dict:
        """Private documents: streamed by an authenticated staff endpoint, never public URLs."""
        request = self.context.get("request")
        return {
            field: _abs(request, reverse("staff-verification-image", args=[obj.pk, field]))
            for field in ("id_front_image", "id_back_image", "selfie_image")
            if getattr(obj, field)
        }

    def get_fundi(self, obj):
        profile = getattr(obj.user, "fundi_profile", None)
        return {"id": str(profile.pk), "business_name": profile.business_name, "status": profile.status} if profile else None

    def get_reviewed_by(self, obj):
        return (obj.reviewed_by.full_name or obj.reviewed_by.email) if obj.reviewed_by else None

    def get_previous_submissions(self, obj) -> int:
        return IV.objects.filter(user_id=obj.user_id).exclude(pk=obj.pk).count()


class FundiSerializer(serializers.ModelSerializer):
    user = PersonSerializer(read_only=True)
    services = serializers.SerializerMethodField()
    is_discoverable = serializers.SerializerMethodField()
    open_bookings = serializers.IntegerField(read_only=True)

    class Meta:
        model = FundiProfile
        fields = [
            "id", "business_name", "status", "status_reason", "is_available", "is_discoverable", "area_text",
            "district", "region", "services", "rating_avg", "rating_count", "completed_jobs_count", "open_bookings",
            "profile_views", "user", "created_at",
        ]

    def get_is_discoverable(self, obj) -> bool:
        return obj.pk in self.context.get("discoverable_ids", set())

    def get_services(self, obj) -> list[str]:
        return [s.category.name_en for s in obj.services.all()]


class BookingEventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = BookingEvent
        fields = ["from_status", "to_status", "actor", "actor_role", "note", "created_at"]

    def get_actor(self, obj):
        return (obj.actor.full_name or obj.actor.email) if obj.actor else None


class BookingSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name_en")
    client = PersonSerializer(read_only=True)
    fundi = serializers.SerializerMethodField()
    events = BookingEventSerializer(many=True, read_only=True)
    review = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "reference", "status", "category", "description", "job_address", "landmark", "client", "fundi",
            "quoted_price_tzs", "final_price_tzs", "payment_status", "dispute_reason", "cancellation_reason",
            "cancelled_by", "created_at", "responded_at", "completed_at", "closed_at", "events", "review",
        ]

    def get_fundi(self, obj):
        return {
            "id": str(obj.fundi_id),
            "business_name": obj.fundi.business_name,
            "phone_number": obj.fundi.user.phone_number,
            "status": obj.fundi.status,
        }

    def get_review(self, obj):
        review = getattr(obj, "review", None)
        return {"rating": review.rating, "comment": review.comment} if review else None


class StaffActionSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = StaffAction
        fields = ["id", "actor", "action", "target_type", "target_id", "target_label", "note", "created_at"]

    def get_actor(self, obj):
        return (obj.actor.full_name or obj.actor.email) if obj.actor else "system"


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)


class RejectSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=IV.RejectionReason.choices)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class BoxSerializer(serializers.Serializer):
    box = serializers.ListField(child=serializers.FloatField(min_value=0, max_value=1), min_length=4, max_length=4)
