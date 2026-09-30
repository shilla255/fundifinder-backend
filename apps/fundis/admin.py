from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin

from . import services
from .models import FavoriteFundi, FundiProfile, FundiService, WorkPhoto


class WorkPhotoInline(admin.TabularInline):
    model = WorkPhoto
    extra = 0
    fields = ["image", "caption", "category", "sort_order"]


class FundiServiceInline(admin.TabularInline):
    model = FundiService
    extra = 0
    autocomplete_fields = ["category"]


@admin.register(FundiProfile)
class FundiProfileAdmin(GISModelAdmin):
    list_display = [
        "business_name",
        "user",
        "status",
        "identity_status",
        "is_available",
        "district",
        "rating_avg",
        "completed_jobs_count",
    ]
    list_filter = ["status", "user__identity_status", "is_available", "region"]
    search_fields = ["business_name", "user__email", "user__phone_number", "district"]
    raw_id_fields = ["user"]
    readonly_fields = ["status", "activated_at", "rating_avg", "rating_count", "completed_jobs_count"]
    inlines = [FundiServiceInline, WorkPhotoInline]
    actions = ["suspend_selected", "reinstate_selected"]

    @admin.display(description="Identity")
    def identity_status(self, obj):
        return obj.user.get_identity_status_display()

    @admin.action(description="Suspend selected fundis (cancels jobs not yet started)")
    def suspend_selected(self, request, queryset):
        for profile in queryset:
            services.suspend(profile, reason=profile.status_reason or "Suspended by admin", actor=request.user)
        self.message_user(request, f"Suspended {queryset.count()} fundi(s).")

    @admin.action(description="Reinstate selected suspended fundis")
    def reinstate_selected(self, request, queryset):
        for profile in queryset:
            try:
                services.reinstate(profile)
            except services.FundiError as exc:
                self.message_user(request, f"{profile}: {exc}", level=messages.WARNING)


@admin.register(FavoriteFundi)
class FavoriteFundiAdmin(admin.ModelAdmin):
    list_display = ["user", "fundi", "created_at"]
    raw_id_fields = ["user", "fundi"]
