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
    nida_number = serializers.CharField(max_length=32, write_only=True)
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


class VerificationStatusSerializer(serializers.ModelSerializer):
    """What the user sees about their own latest submission. No images, no full NIDA number."""

    rejection_reason_display = serializers.CharField(
        source="get_rejection_reason_display", read_only=True
    )

    class Meta:
        model = IdentityVerification
        fields = [
            "id",
            "status",
            "full_name",
            "nida_last4",
            "rejection_reason",
            "rejection_reason_display",
            "created_at",
            "reviewed_at",
        ]
        read_only_fields = fields
