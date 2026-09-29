from django.db import transaction
from django.utils import timezone

from apps.notifications.services import notify

from .models import FundiProfile


class FundiError(Exception):
    pass


def activate(profile: FundiProfile) -> FundiProfile:
    """Publish a draft or paused profile. Search visibility also needs identity verification."""
    if profile.status not in (FundiProfile.Status.DRAFT, FundiProfile.Status.PAUSED):
        raise FundiError(f"A {profile.get_status_display().lower()} profile cannot be activated.")
    if profile.base_location is None:
        raise FundiError("Set your work location before activating.")
    if not profile.services.filter(is_active=True).exists():
        raise FundiError("Add at least one service before activating.")
    profile.status = FundiProfile.Status.ACTIVE
    profile.activated_at = profile.activated_at or timezone.now()
    profile.save(update_fields=["status", "activated_at", "updated_at"])
    return profile


def pause(profile: FundiProfile) -> FundiProfile:
    if profile.status != FundiProfile.Status.ACTIVE:
        raise FundiError("Only an active profile can be paused.")
    profile.status = FundiProfile.Status.PAUSED
    profile.save(update_fields=["status", "updated_at"])
    return profile


@transaction.atomic
def suspend(profile: FundiProfile, reason: str, actor=None, ban: bool = False) -> FundiProfile:
    """Admin action. Cancels jobs that haven't started; jobs in progress are left for support."""
    from apps.bookings.services import cancel_open_bookings_for_fundi

    profile.status = FundiProfile.Status.BANNED if ban else FundiProfile.Status.SUSPENDED
    profile.status_reason = reason
    profile.save(update_fields=["status", "status_reason", "updated_at"])
    cancel_open_bookings_for_fundi(profile, reason="Fundi is no longer available.", actor=actor)
    transaction.on_commit(lambda: notify(profile.user, "fundi.suspended"))
    return profile


def reinstate(profile: FundiProfile) -> FundiProfile:
    if profile.status != FundiProfile.Status.SUSPENDED:
        raise FundiError("Only suspended profiles can be reinstated.")
    profile.status = FundiProfile.Status.ACTIVE
    profile.status_reason = ""
    profile.save(update_fields=["status", "status_reason", "updated_at"])
    return profile
