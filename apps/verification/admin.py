from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html

from . import services
from .models import IdentityVerification, VerificationEvent
from .views import private_image


class VerificationEventInline(admin.TabularInline):
    model = VerificationEvent
    extra = 0
    can_delete = False
    fields = ["created_at", "from_status", "to_status", "actor", "reason"]
    readonly_fields = fields


@admin.register(IdentityVerification)
class IdentityVerificationAdmin(admin.ModelAdmin):
    """Review queue. Open a pending submission, compare the photos, then Approve or Reject."""

    list_display = [
        "full_name",
        "user",
        "nida_last4",
        "status",
        "is_duplicate_nida",
        "created_at",
        "reviewed_by",
    ]
    list_filter = ["status", "is_duplicate_nida", "method"]
    search_fields = ["full_name", "nida_last4", "user__email", "user__phone_number"]
    ordering = ["created_at"]
    exclude = ["id_front_image", "id_back_image", "selfie_image"]
    readonly_fields = [
        "user",
        "full_name",
        "date_of_birth",
        "masked_nida",
        "dob_hint",
        "is_duplicate_nida",
        "id_front",
        "id_back",
        "selfie",
        "status",
        "method",
        "reviewed_by",
        "reviewed_at",
    ]
    inlines = [VerificationEventInline]
    change_form_template = "admin/verification/identityverification/change_form.html"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status != IdentityVerification.Status.PENDING:
            fields += ["rejection_reason", "review_note"]
        return fields

    def get_urls(self):
        return [
            path(
                "<uuid:pk>/image/<str:field>/",
                self.admin_site.admin_view(private_image),
                name="verification_private_image",
            ),
            *super().get_urls(),
        ]

    def _image(self, obj, field):
        if not getattr(obj, field):
            return "—"
        url = reverse("admin:verification_private_image", args=[obj.pk, field])
        return format_html('<a href="{0}" target="_blank"><img src="{0}" style="max-height:320px"></a>', url)

    @admin.display(description="ID front")
    def id_front(self, obj):
        return self._image(obj, "id_front_image")

    @admin.display(description="ID back")
    def id_back(self, obj):
        return self._image(obj, "id_back_image")

    @admin.display(description="Selfie")
    def selfie(self, obj):
        return self._image(obj, "selfie_image")

    @admin.display(description="NIDA number")
    def masked_nida(self, obj):
        n = obj.nida_number
        return f"{n[:8]}-•••••-•••••-{n[-2:]}" if len(n) == 20 else f"…{obj.nida_last4}"

    @admin.display(description="Birth date matches NIDA number", boolean=True)
    def dob_hint(self, obj):
        return obj.dob_matches_nida

    def response_change(self, request, obj):
        action = "_approve" if "_approve" in request.POST else "_reject" if "_reject" in request.POST else None
        if action is None:
            return super().response_change(request, obj)
        try:
            if action == "_approve":
                services.approve(obj, request.user)
                self.message_user(request, f"Approved {obj.full_name}.")
            else:
                services.reject(obj, request.user, obj.rejection_reason, obj.review_note)
                self.message_user(request, f"Rejected {obj.full_name}.")
        except services.VerificationError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(request.path)
        return HttpResponseRedirect(reverse("admin:verification_identityverification_changelist"))


@admin.register(VerificationEvent)
class VerificationEventAdmin(admin.ModelAdmin):
    list_display = ["user", "from_status", "to_status", "actor", "created_at"]
    list_filter = ["to_status"]
    search_fields = ["user__email", "user__phone_number"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
