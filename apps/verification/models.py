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


def portrait_upload_path(instance, filename):
    return f"portraits/{uuid.uuid4().hex}.jpg"


class IdentityVerification(BaseModel):
    """One identity submission. Rows are never overwritten: a resubmission is a new row,
    so the history (and any fraud signal) is kept.

    Accepted documents, in priority order: NIDA card, driving licence, passport.
    Today staff review uploaded photos plus a selfie; `method` leaves room for an
    automated NIDA check later. The person's public photo (their FundiFinder avatar)
    is always the portrait cut from their approved document — see `portrait.py`.
    """

    class DocumentType(models.TextChoices):
        NIDA = "nida", "NIDA card"
        DRIVING_LICENCE = "driving_licence", "Driving licence"
        PASSPORT = "passport", "Passport"

    # Lower number = preferred. A verified user may upgrade to a better document, never downgrade.
    DOCUMENT_PRIORITY = {DocumentType.NIDA: 0, DocumentType.DRIVING_LICENCE: 1, DocumentType.PASSPORT: 2}

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
        INVALID_DOCUMENT = "invalid_document", "Not a valid ID document"
        NO_PORTRAIT = "no_portrait", "The photo on the document isn't clear"
        DUPLICATE_IDENTITY = "duplicate_identity", "ID already used by another account"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="identity_verifications"
    )
    full_name = models.CharField(max_length=150, help_text="Name exactly as printed on the ID.")
    date_of_birth = models.DateField()
    document_type = models.CharField(max_length=20, choices=DocumentType.choices, default=DocumentType.NIDA)
    document_number_encrypted = models.TextField(editable=False)
    document_number_hash = models.CharField(max_length=64, editable=False, db_index=True)
    document_last4 = models.CharField(max_length=4, editable=False)

    id_front_image = models.ImageField(storage=private_storage, upload_to=document_upload_path)
    id_back_image = models.ImageField(
        storage=private_storage, upload_to=document_upload_path, blank=True
    )
    selfie_image = models.ImageField(storage=private_storage, upload_to=document_upload_path)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.MANUAL)
    # Another account already has an approved verification with this document.
    is_duplicate_document = models.BooleanField(default=False)

    # Where the person's photo sits on `id_front_image`, as fractions of the image
    # (left, top, width, height). Found automatically; staff can adjust it.
    portrait_box = models.JSONField(null=True, blank=True)
    # How the box was found: "nida_api", "face_detection" or "template" (fixed position per document).
    portrait_method = models.CharField(max_length=20, blank=True)
    # The cut-out face. Public: once approved it is the person's avatar.
    portrait = models.ImageField(upload_to=portrait_upload_path, blank=True, editable=False)

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
                fields=["document_type", "document_number_hash"],
                condition=Q(status="approved"),
                name="one_approved_verification_per_document",
            ),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.get_document_type_display()} …{self.document_last4}) – {self.get_status_display()}"

    @property
    def document_number(self) -> str:
        from apps.core.crypto import decrypt

        return decrypt(self.document_number_encrypted)

    @property
    def priority(self) -> int:
        return self.DOCUMENT_PRIORITY[self.document_type]

    @property
    def dob_matches_nida(self) -> bool | None:
        """Reviewer hint: NIDA numbers start with the holder's birth date (YYYYMMDD).
        A mismatch is worth a closer look, not an automatic rejection. None for other documents."""
        if self.document_type != self.DocumentType.NIDA:
            return None
        return self.document_number[:8] == self.date_of_birth.strftime("%Y%m%d")


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
