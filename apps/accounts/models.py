import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BaseModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email=None, password=None, **extra_fields):
        email = self.normalize_email(email).lower() if email else None
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Superusers need an email address.")
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """One account per person. Becoming a fundi adds a FundiProfile; there is no role field.

    People sign in with Google (email) or, once an SMS gateway exists, a phone OTP.
    `phone_number` may be set before it is verified so fundis and clients can call
    each other; only verified numbers are unique and usable for login.
    """

    class Language(models.TextChoices):
        SWAHILI = "sw", "Kiswahili"
        ENGLISH = "en", "English"

    class IdentityStatus(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        PENDING = "pending", "Pending review"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
        REVERIFICATION_REQUIRED = "reverification_required", "Re-verification required"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone_number = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    avatar_url = models.URLField(blank=True)
    preferred_language = models.CharField(
        max_length=2, choices=Language.choices, default=Language.SWAHILI
    )
    # Current identity state. The attempts behind it live in apps.verification.
    identity_status = models.CharField(
        max_length=32,
        choices=IdentityStatus.choices,
        default=IdentityStatus.UNVERIFIED,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=Q(phone_verified_at__isnull=False),
                name="unique_verified_phone_number",
            ),
            models.CheckConstraint(
                condition=Q(email__isnull=False) | Q(phone_number__isnull=False),
                name="user_has_email_or_phone",
            ),
        ]

    def __str__(self):
        return self.full_name or self.email or self.phone_number or str(self.id)

    @property
    def is_identity_verified(self) -> bool:
        return self.identity_status == self.IdentityStatus.VERIFIED

    @property
    def phone_verified(self) -> bool:
        return self.phone_verified_at is not None


class AuthIdentity(BaseModel):
    """A third-party login linked to a user. Keyed by the provider's stable subject ID,
    not email, because a Google account's email can change."""

    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="identities")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    last_used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "subject"], name="unique_provider_subject"),
        ]

    def __str__(self):
        return f"{self.provider}:{self.email or self.subject}"


class OTPChallenge(BaseModel):
    class Purpose(models.TextChoices):
        LOGIN = "login", "Log in"
        VERIFY_PHONE = "verify_phone", "Verify phone number"

    phone_number = models.CharField(max_length=16, db_index=True)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    # Set for VERIFY_PHONE: the signed-in user claiming the number.
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"{self.purpose} {self.phone_number}"
