import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import storages
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


def private_storage():
    return storages["private"]


def document_upload_path(instance, filename):
    # Random names: the original filename can contain the person's name or ID number.
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"verification/{instance.user_id}/{uuid.uuid4().hex}{ext}"


class IdentityVerification(BaseModel):
    """One identity submission. Rows are never overwritten: a resubmission is a new row,
    so the history (and any fraud signal) is kept.

    Today this is a manual review of uploaded NIDA card photos plus a selfie.
    `method` leaves room for an automated NIDA check later.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded by a newer approval"
        REVOKED = "revoked", "Revoked"

    class Method(models.TextChoices):
        MANUAL = "manual_review", "Manual review"
        NIDA_API = "nida_api", "NIDA API"

    class RejectionReason(models.TextChoices):
        UNREADABLE = "unreadable", "Photo unclear or unreadable"
        DETAILS_MISMATCH = "details_mismatch", "Details don't match the ID card"
        FACE_MISMATCH = "face_mismatch", "Selfie doesn't match the ID photo"
        INVALID_DOCUMENT = "invalid_document", "Not a valid NIDA card"
        DUPLICATE_IDENTITY = "duplicate_identity", "ID already used by another account"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="identity_verifications"
    )
    full_name = models.CharField(max_length=150, help_text="Name exactly as printed on the ID.")
    date_of_birth = models.DateField()
    nida_number_encrypted = models.TextField(editable=False)
    nida_number_hash = models.CharField(max_length=64, editable=False, db_index=True)
    nida_last4 = models.CharField(max_length=4, editable=False)

    id_front_image = models.ImageField(storage=private_storage, upload_to=document_upload_path)
    id_back_image = models.ImageField(
        storage=private_storage, upload_to=document_upload_path, blank=True
    )
    selfie_image = models.ImageField(storage=private_storage, upload_to=document_upload_path)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.MANUAL)
    # Another account already has an approved verification with this NIDA number.
    is_duplicate_nida = models.BooleanField(default=False)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(
        max_length=30, choices=RejectionReason.choices, blank=True
    )
    review_note = models.TextField(blank=True, help_text="Internal note; not shown to the user.")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status="pending"),
                name="one_pending_verification_per_user",
            ),
            models.UniqueConstraint(
                fields=["nida_number_hash"],
                condition=Q(status="approved"),
                name="one_approved_verification_per_nida",
            ),
        ]

    def __str__(self):
        return f"{self.full_name} (…{self.nida_last4}) – {self.get_status_display()}"

    @property
    def nida_number(self) -> str:
        from apps.core.crypto import decrypt

        return decrypt(self.nida_number_encrypted)

    @property
    def dob_matches_nida(self) -> bool:
        """Reviewer hint: NIDA numbers start with the holder's birth date (YYYYMMDD).
        A mismatch is worth a closer look, not an automatic rejection."""
        return self.nida_number[:8] == self.date_of_birth.strftime("%Y%m%d")


class VerificationEvent(BaseModel):
    """Audit trail of every change to a user's identity status."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_events"
    )
    verification = models.ForeignKey(
        IdentityVerification, null=True, blank=True, on_delete=models.SET_NULL, related_name="events"
    )
    from_status = models.CharField(max_length=32)
    to_status = models.CharField(max_length=32)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user}: {self.from_status} → {self.to_status}"
