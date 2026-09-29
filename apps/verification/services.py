import re

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.crypto import encrypt, keyed_hash
from apps.notifications.services import notify

from .models import IdentityVerification as IV
from .models import VerificationEvent

Identity = User.IdentityStatus

# Statuses from which a user may submit (again).
SUBMITTABLE = {Identity.UNVERIFIED, Identity.REJECTED, Identity.REVERIFICATION_REQUIRED}


class VerificationError(Exception):
    pass


def normalize_nida(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 20:
        raise VerificationError("A NIDA number has 20 digits.")
    return digits


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
def submit(user, *, nida_number, full_name, date_of_birth, id_front_image, selfie_image, id_back_image=None):
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.identity_status not in SUBMITTABLE:
        messages = {
            Identity.PENDING: "Your previous submission is still being reviewed.",
            Identity.VERIFIED: "Your identity is already verified.",
            Identity.REVOKED: "Your verification was revoked. Please contact support.",
        }
        raise VerificationError(messages[user.identity_status])

    nida = normalize_nida(nida_number)
    nida_hash = keyed_hash(nida)
    duplicate = IV.objects.filter(nida_number_hash=nida_hash, status=IV.Status.APPROVED).exclude(user=user).exists()

    verification = IV.objects.create(
        user=user,
        full_name=full_name.strip(),
        date_of_birth=date_of_birth,
        nida_number_encrypted=encrypt(nida),
        nida_number_hash=nida_hash,
        nida_last4=nida[-4:],
        id_front_image=id_front_image,
        id_back_image=id_back_image or "",
        selfie_image=selfie_image,
        is_duplicate_nida=duplicate,
    )
    _set_identity_status(user, Identity.PENDING, actor=user, verification=verification)
    return verification


@transaction.atomic
def approve(verification: IV, reviewer) -> IV:
    verification = IV.objects.select_for_update().select_related("user").get(pk=verification.pk)
    if verification.status != IV.Status.PENDING:
        raise VerificationError("Only pending submissions can be approved.")
    taken = (
        IV.objects.filter(nida_number_hash=verification.nida_number_hash, status=IV.Status.APPROVED)
        .exclude(user=verification.user)
        .exists()
    )
    if taken:
        raise VerificationError(
            "This NIDA number is already verified on another account. Reject as duplicate, "
            "or revoke the other account's verification first."
        )

    user = verification.user
    IV.objects.filter(user=user, status=IV.Status.APPROVED).update(status=IV.Status.SUPERSEDED)
    verification.status = IV.Status.APPROVED
    verification.reviewed_by = reviewer
    verification.reviewed_at = timezone.now()
    verification.rejection_reason = ""
    verification.save()
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
    profile = FundiProfile.objects.filter(user=user).first()
    if profile:
        suspend(profile, reason=reason, actor=actor, ban=True)
