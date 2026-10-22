from django.contrib import admin

from .models import Broadcast, Device, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "kind", "title", "created_at", "read_at"]
    list_filter = ["kind"]
    search_fields = ["user__email", "user__phone_number", "title"]
    raw_id_fields = ["user"]


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "platform", "last_seen_at"]
    list_filter = ["platform"]
    raw_id_fields = ["user"]


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ["title_en", "audience", "recipients", "pushed", "sent_by", "created_at"]
    readonly_fields = ["recipients", "pushed", "sent_by"]

    def has_add_permission(self, request):
        return False  # sending happens in the staff console, which also fans the message out
