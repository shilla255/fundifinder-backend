from django.contrib import admin

from .models import StaffAction


@admin.register(StaffAction)
class StaffActionAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor", "action", "target_type", "target_label"]
    list_filter = ["action", "target_type"]
    search_fields = ["target_label", "target_id", "note", "actor__email"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
