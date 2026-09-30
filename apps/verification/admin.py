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
        "document_type",
        "document_last4",
        "status",
        "is_duplicate_document",
        "created_at",
        "reviewed_by",
    ]
    list_filter = ["status", "document_type", "is_duplicate_document", "method"]
    search_fields = ["full_name", "document_last4", "user__email", "user__phone_number"]
    ordering = ["created_at"]
    exclude = ["id_front_image", "id_back_image", "selfie_image"]
    readonly_fields = [
        "user",
        "document_type",
        "full_name",
        "date_of_birth",
        "masked_number",
        "dob_hint",
        "is_duplicate_document",
        "portrait_preview",
        "portrait_method",
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

    @admin.display(description="Document number")
    def masked_number(self, obj):
        n = obj.document_number
        if obj.document_type == IdentityVerification.DocumentType.NIDA and len(n) == 20:
            return f"{n[:8]}-•••••-•••••-{n[-2:]}"
        return f"{'•' * max(len(n) - 4, 0)}{obj.document_last4}"

    @admin.display(description="Birth date matches NIDA number", boolean=True)
    def dob_hint(self, obj):
        return obj.dob_matches_nida

    @admin.display(description="Portrait (public photo once approved)")
    def portrait_preview(self, obj):
        box = obj.portrait_box or ["", "", "", ""]
        img = format_html('<img src="{}" style="height:160px;border-radius:16px">', obj.portrait.url) if obj.portrait else "—"
        return format_html(
            '{}<p style="margin-top:8px">Crop box on the ID front (left, top, width, height as 0–1 fractions):</p>'
            '<input name="_portrait_box" value="{}" style="width:260px"> '
            '<input type="submit" name="_recrop" value="Re-cut portrait">',
            img,
            ", ".join(str(v) for v in box),
        )

    def response_change(self, request, obj):
        if "_recrop" in request.POST:
            try:
                box = [float(v) for v in request.POST.get("_portrait_box", "").split(",")]
                if len(box) != 4:
                    raise ValueError
                services.recrop_portrait(obj, box)
                self.message_user(request, "Portrait updated.")
            except (ValueError, services.VerificationError):
                self.message_user(request, "Enter four numbers between 0 and 1, e.g. 0.03, 0.24, 0.3, 0.62", level=messages.ERROR)
            return HttpResponseRedirect(request.path)
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
