from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "kind", "title", "created_at", "read_at"]
    list_filter = ["kind"]
    search_fields = ["user__email", "user__phone_number", "title"]
    raw_id_fields = ["user"]
