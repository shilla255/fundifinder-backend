from rest_framework import serializers

from apps.core.phone import PhoneNumberField

from .models import OTPChallenge, User


class UserSerializer(serializers.ModelSerializer):
    phone_number = PhoneNumberField(required=False, allow_null=True)
    phone_verified = serializers.BooleanField(read_only=True)
    is_fundi = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone_number",
            "phone_verified",
            "full_name",
            "avatar_url",
            "preferred_language",
            "identity_status",
            "is_fundi",
            "date_joined",
        ]
        read_only_fields = ["id", "email", "avatar_url", "identity_status", "date_joined"]

    def get_is_fundi(self, obj) -> bool:
        return hasattr(obj, "fundi_profile")

    def validate_phone_number(self, value):
        user = self.instance
        if user and user.phone_verified and value != user.phone_number:
            raise serializers.ValidationError(
                "A verified phone number can only be changed by verifying the new number."
            )
        if value is None and user and not user.email:
            raise serializers.ValidationError("Your account needs a phone number.")
        if value and (
            User.objects.filter(phone_number=value, phone_verified_at__isnull=False)
            .exclude(pk=getattr(user, "pk", None))
            .exists()
        ):
            raise serializers.ValidationError("This phone number belongs to another account.")
        return value


class GoogleSignInSerializer(serializers.Serializer):
    id_token = serializers.CharField()


class OTPRequestSerializer(serializers.Serializer):
    phone_number = PhoneNumberField()
    purpose = serializers.ChoiceField(
        choices=OTPChallenge.Purpose.choices, default=OTPChallenge.Purpose.LOGIN
    )


class OTPVerifySerializer(OTPRequestSerializer):
    code = serializers.RegexField(r"^\d{6}$")
