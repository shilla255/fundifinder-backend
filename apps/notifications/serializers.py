from rest_framework import serializers

from .models import Device, Notification


class NotificationSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "data", "image", "read_at", "created_at"]
        read_only_fields = fields

    def get_image(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.image.url) if request else obj.image.url


class DeviceSerializer(serializers.Serializer):
    # Not a ModelSerializer: its unique-token check would reject a phone changing accounts.
    token = serializers.CharField(max_length=300)
    platform = serializers.ChoiceField(choices=Device.Platform.choices, default=Device.Platform.ANDROID)
