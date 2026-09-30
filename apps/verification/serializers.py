from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import IdentityVerification


def validate_image_size(image):
    limit = settings.VERIFICATION_MAX_IMAGE_MB * 1024 * 1024
    if image.size > limit:
        raise serializers.ValidationError(
            f"Images must be smaller than {settings.VERIFICATION_MAX_IMAGE_MB} MB."
        )
    return image


class VerificationSubmitSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(
        choices=IdentityVerification.DocumentType.choices, default=IdentityVerification.DocumentType.NIDA
    )
    document_number = serializers.CharField(max_length=32, write_only=True, required=False)
    # Older clients send the NIDA number under this name.
    nida_number = serializers.CharField(max_length=32, write_only=True, required=False)
    full_name = serializers.CharField(max_length=150)
    date_of_birth = serializers.DateField()
    id_front_image = serializers.ImageField(validators=[validate_image_size])
    id_back_image = serializers.ImageField(validators=[validate_image_size], required=False)
    selfie_image = serializers.ImageField(validators=[validate_image_size])

    def validate_date_of_birth(self, value):
        today = timezone.localdate()
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise serializers.ValidationError("You must be at least 18 years old.")
        if age > 100:
            raise serializers.ValidationError("Check the date of birth.")
        return value

    def validate(self, attrs):
        number = attrs.pop("document_number", None) or attrs.pop("nida_number", None)
        attrs.pop("nida_number", None)
        if not number:
            raise serializers.ValidationError({"document_number": "This field is required."})
        attrs["document_number"] = number
        return attrs


class VerificationStatusSerializer(serializers.ModelSerializer):
    """What the user sees about their own latest submission. No images, no full NIDA number."""

    rejection_reason_display = serializers.CharField(
        source="get_rejection_reason_display", read_only=True
    )
    document_type_display = serializers.CharField(source="get_document_type_display", read_only=True)
    portrait = serializers.ImageField(read_only=True)

    class Meta:
        model = IdentityVerification
        fields = [
            "id",
            "status",
            "document_type",
            "document_type_display",
            "full_name",
            "document_last4",
            "portrait",
            "rejection_reason",
            "rejection_reason_display",
            "created_at",
            "reviewed_at",
        ]
        read_only_fields = fields
