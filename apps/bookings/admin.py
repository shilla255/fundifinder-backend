from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin

from . import services
from .models import Booking, BookingEvent, Review


class BookingEventInline(admin.TabularInline):
    model = BookingEvent
    extra = 0
    can_delete = False
    fields = ["created_at", "from_status", "to_status", "actor_role", "actor", "note"]
    readonly_fields = fields


@admin.register(Booking)
class BookingAdmin(GISModelAdmin):
    list_display = ["reference", "client", "fundi", "category", "status", "payment_status", "created_at"]
    list_filter = ["status", "payment_status", "category"]
    search_fields = ["reference", "client__email", "client__phone_number", "fundi__business_name"]
    raw_id_fields = ["client", "fundi"]
    readonly_fields = [
        "reference",
        "status",
        "expires_at",
        "responded_at",
        "started_at",
        "completed_at",
        "closed_at",
        "cancelled_at",
        "cancelled_by",
    ]
    inlines = [BookingEventInline]
    actions = ["admin_cancel"]

    @admin.action(description="Cancel selected bookings (not yet started)")
    def admin_cancel(self, request, queryset):
        for booking in queryset:
            try:
                services.transition(
                    booking, "cancel", actor=request.user, role=Booking.Party.ADMIN,
                    note="Cancelled by FundiFinder support",
                )
            except services.BookingError as exc:
                self.message_user(request, f"{booking}: {exc}", level=messages.WARNING)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["booking", "fundi", "client", "rating", "created_at"]
    list_filter = ["rating"]
    raw_id_fields = ["booking", "fundi", "client"]
