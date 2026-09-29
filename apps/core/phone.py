import phonenumbers
from django.core.exceptions import ValidationError
from rest_framework import serializers

DEFAULT_REGION = "TZ"


def normalize_phone(raw: str, region: str = DEFAULT_REGION) -> str:
    """Return the number in E.164 form (+2557XXXXXXXX).

    Accepts local (0712 345 678), international (+255712345678) and
    bare-country-code (255712345678) formats.
    """
    value = (raw or "").strip().replace(" ", "").replace("-", "")
    if value.startswith("255") and not value.startswith("+"):
        value = f"+{value}"
    try:
        parsed = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError("Enter a valid phone number.") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValidationError("Enter a valid phone number.")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


class PhoneNumberField(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return normalize_phone(value)
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
