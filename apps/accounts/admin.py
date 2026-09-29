from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AuthIdentity, OTPChallenge, User


class AuthIdentityInline(admin.TabularInline):
    model = AuthIdentity
    extra = 0
    readonly_fields = ["provider", "subject", "email", "last_used_at"]
    can_delete = False


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["-date_joined"]
    list_display = [
        "__str__",
        "email",
        "phone_number",
        "phone_verified_at",
        "identity_status",
        "is_active",
        "date_joined",
    ]
    list_filter = ["identity_status", "is_active", "is_staff", "preferred_language"]
    search_fields = ["email", "phone_number", "full_name"]
    readonly_fields = ["identity_status", "date_joined", "last_login"]
    inlines = [AuthIdentityInline]
    fieldsets = [
        (None, {"fields": ["email", "phone_number", "phone_verified_at", "password"]}),
        ("Profile", {"fields": ["full_name", "avatar_url", "preferred_language"]}),
        ("Trust", {"fields": ["identity_status"]}),
        (
            "Permissions",
            {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]},
        ),
        ("Dates", {"fields": ["date_joined", "last_login", "deleted_at"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "password1", "password2"]}),
    ]


@admin.register(OTPChallenge)
class OTPChallengeAdmin(admin.ModelAdmin):
    list_display = ["phone_number", "purpose", "created_at", "expires_at", "attempts", "consumed_at"]
    list_filter = ["purpose"]
    search_fields = ["phone_number"]
    exclude = ["code_hash"]
    readonly_fields = [
        "phone_number",
        "purpose",
        "user",
        "expires_at",
        "attempts",
        "consumed_at",
        "ip_address",
    ]
