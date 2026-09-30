import logging
import re

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.crypto import encrypt, keyed_hash
from apps.notifications.services import notify

from . import portrait as portraits
from .models import IdentityVerification as IV
from .models import VerificationEvent

log = logging.getLogger(__name__)
Identity = User.IdentityStatus
Doc = IV.DocumentType

# Statuses from which a user may submit (again).
SUBMITTABLE = {Identity.UNVERIFIED, Identity.REJECTED, Identity.REVERIFICATION_REQUIRED}


class VerificationError(Exception):
    pass


def normalize_nida(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 20:
        raise VerificationError("A NIDA number has 20 digits.")
    return digits


def normalize_document_number(document_type: str, raw: str) -> str:
    """Canonical form of a document number, so the same document always hashes the same."""
    if document_type == Doc.NIDA:
        return normalize_nida(raw)
    value = re.sub(r"[\s\-/]", "", raw or "").upper()
    if document_type == Doc.DRIVING_LICENCE:
        # Tanzanian licences carry a 10-digit number; allow older 8–12 character formats.
        if not re.fullmatch(r"[A-Z0-9]{8,12}", value) or not any(c.isdigit() for c in value):
            raise VerificationError("Enter the licence number as printed on the card.")
        return value
    if document_type == Doc.PASSPORT:
        # Letters then digits, e.g. AB1234567.
        if not re.fullmatch(r"[A-Z]{1,2}[0-9]{6,8}", value):
            raise VerificationError("Enter the passport number as printed, e.g. AB1234567.")
        return value
    raise VerificationError("Choose NIDA card, driving licence or passport.")


def current_document(user) -> IV | None:
    return IV.objects.filter(user=user, status=IV.Status.APPROVED).first()


def submittable_documents(user) -> list[str]:
    if user.identity_status in (Identity.PENDING, Identity.REVOKED):
        return []
    if IV.objects.filter(user=user, status=IV.Status.PENDING).exists():
        return []
    if user.identity_status == Identity.VERIFIED:
        approved = current_document(user)
        if approved:
            return [str(d) for d, p in IV.DOCUMENT_PRIORITY.items() if p < approved.priority]
        return []
    return [str(d) for d in IV.DOCUMENT_PRIORITY]


def _set_identity_status(user, new_status, *, actor=None, verification=None, reason=""):
    VerificationEvent.objects.create(
        user=user,
        verification=verification,
        from_status=user.identity_status,
        to_status=new_status,
        actor=actor,
        reason=reason,
    )
    user.identity_status = new_status
    user.save(update_fields=["identity_status"])


@transaction.atomic
def submit(
    user, *, document_number, full_name, date_of_birth, id_front_image, selfie_image,
    id_back_image=None, document_type=Doc.NIDA,
):
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.identity_status == Identity.VERIFIED:
        # Verified people may upgrade to a better document (e.g. passport → NIDA), not sideways or down.
        approved = current_document(user)
        if approved and IV.DOCUMENT_PRIORITY[document_type] >= approved.priority:
            raise VerificationError("Your identity is already verified.")
        if IV.objects.filter(user=user, status=IV.Status.PENDING).exists():
            raise VerificationError("Your previous submission is still being reviewed.")
    elif user.identity_status not in SUBMITTABLE:
        messages = {
            Identity.PENDING: "Your previous submission is still being reviewed.",
            Identity.REVOKED: "Your verification was revoked. Please contact support.",
        }
        raise VerificationError(messages[user.identity_status])

    number = normalize_document_number(document_type, document_number)
    number_hash = keyed_hash(number if document_type == Doc.NIDA else f"{document_type}:{number}")
    duplicate = (
        IV.objects.filter(document_type=document_type, document_number_hash=number_hash, status=IV.Status.APPROVED)
        .exclude(user=user)
        .exists()
    )

    verification = IV.objects.create(
        user=user,
        document_type=document_type,
        full_name=full_name.strip(),
        date_of_birth=date_of_birth,
        document_number_encrypted=encrypt(number),
        document_number_hash=number_hash,
        document_last4=number[-4:],
        id_front_image=id_front_image,
        id_back_image=id_back_image or "",
        selfie_image=selfie_image,
        is_duplicate_document=duplicate,
    )
    # Find the face now so the reviewer sees the future avatar next to the selfie.
    _store_portrait(verification)
    if user.identity_status != Identity.VERIFIED:
        _set_identity_status(user, Identity.PENDING, actor=user, verification=verification)
    return verification


def _store_portrait(verification: IV, box=None) -> bool:
    try:
        result = portraits.extract(verification, box=box)
    except Exception:  # noqa: BLE001 — never block a submission on image processing
        log.exception("Portrait extraction failed for %s", verification.pk)
        return False
    if not result:
        return False
    if verification.portrait:
        verification.portrait.delete(save=False)
    verification.portrait.save("portrait.jpg", ContentFile(result.image), save=False)
    verification.portrait_box = list(result.box) if result.box else None
    verification.portrait_method = result.method
    verification.save(update_fields=["portrait", "portrait_box", "portrait_method", "updated_at"])
    return True


def recrop_portrait(verification: IV, box) -> IV:
    """Staff fix: cut the portrait from a hand-picked box. Updates the live avatar if this is
    the person's current document."""
    left, top, width, height = (float(v) for v in box)
    if not (0 <= left < 1 and 0 <= top < 1 and 0 < width <= 1 and 0 < height <= 1):
        raise VerificationError("The box must be fractions between 0 and 1.")
    verification = IV.objects.select_related("user").get(pk=verification.pk)
    _store_portrait(verification, box=(left, top, width, height))
    if verification.status == IV.Status.APPROVED:
        _publish_portrait(verification)
    return verification


def _publish_portrait(verification: IV):
    """Make the approved document's portrait the person's public photo."""
    user = verification.user
    user.portrait = verification.portrait.name if verification.portrait else ""
    user.save(update_fields=["portrait"])


@transaction.atomic
def approve(verification: IV, reviewer) -> IV:
    verification = IV.objects.select_for_update().select_related("user").get(pk=verification.pk)
    if verification.status != IV.Status.PENDING:
        raise VerificationError("Only pending submissions can be approved.")
    taken = (
        IV.objects.filter(
            document_type=verification.document_type,
            document_number_hash=verification.document_number_hash,
            status=IV.Status.APPROVED,
        )
        .exclude(user=verification.user)
        .exists()
    )
    if taken:
        raise VerificationError(
            "This document is already verified on another account. Reject as duplicate, "
            "or revoke the other account's verification first."
        )
    if not verification.portrait:
        _store_portrait(verification)
    if not verification.portrait:
        raise VerificationError(
            "No photo could be cut from the document. Set the portrait box, or reject as "
            "\"The photo on the document isn't clear\"."
        )

    user = verification.user
    IV.objects.filter(user=user, status=IV.Status.APPROVED).update(status=IV.Status.SUPERSEDED)
    verification.status = IV.Status.APPROVED
    verification.reviewed_by = reviewer
    verification.reviewed_at = timezone.now()
    verification.rejection_reason = ""
    verification.save()
    _publish_portrait(verification)
    if user.identity_status != Identity.VERIFIED:
        _set_identity_status(user, Identity.VERIFIED, actor=reviewer, verification=verification)
    transaction.on_commit(lambda: notify(user, "verification.approved", sms=True))
    return verification


@transaction.atomic
def reject(verification: IV, reviewer, reason: str, note: str = "") -> IV:
    verification = IV.objects.select_for_update().select_related("user").get(pk=verification.pk)
    if verification.status != IV.Status.PENDING:
        raise VerificationError("Only pending submissions can be rejected.")
    if reason not in IV.RejectionReason.values:
        raise VerificationError("Choose a rejection reason.")

    verification.status = IV.Status.REJECTED
    verification.reviewed_by = reviewer
    verification.reviewed_at = timezone.now()
    verification.rejection_reason = reason
    verification.review_note = note
    verification.save()
    user = verification.user
    if user.identity_status != Identity.VERIFIED:  # a rejected upgrade keeps the current document
        _set_identity_status(user, Identity.REJECTED, actor=reviewer, verification=verification, reason=reason)
    label = IV.RejectionReason(reason).label
    transaction.on_commit(lambda: notify(user, "verification.rejected", sms=True, reason=label))
    return verification


@transaction.atomic
def require_reverification(user, actor, reason: str):
    """E.g. the person's legal details changed or the account looks taken over.
    The fundi drops out of search until a new submission is approved."""
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.identity_status != Identity.VERIFIED:
        raise VerificationError("Only verified users can be asked to re-verify.")
    _set_identity_status(user, Identity.REVERIFICATION_REQUIRED, actor=actor, reason=reason)
    transaction.on_commit(lambda: notify(user, "verification.reverification_required", sms=True))


@transaction.atomic
def revoke(user, actor, reason: str):
    """Fraud (fake or stolen ID). Permanent; also bans the fundi profile if there is one."""
    from apps.fundis.models import FundiProfile
    from apps.fundis.services import suspend

    user = User.objects.select_for_update().get(pk=user.pk)
    IV.objects.filter(user=user, status__in=[IV.Status.APPROVED, IV.Status.PENDING]).update(
        status=IV.Status.REVOKED
    )
    _set_identity_status(user, Identity.REVOKED, actor=actor, reason=reason)
    user.portrait = ""
    user.save(update_fields=["portrait"])
    profile = FundiProfile.objects.filter(user=user).first()
    if profile:
        suspend(profile, reason=reason, actor=actor, ban=True)
