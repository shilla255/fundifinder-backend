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
    transaction.on_commit(lambda: notify(profile.user, "fundi.reinstated"))
    return profile


def stats(profile: FundiProfile) -> dict:
    """Dashboard numbers: activity, reputation and cash earned (as recorded on closed jobs)."""
    from datetime import timedelta

    from django.db.models import Count, Q, Sum
    from django.db.models.functions import TruncMonth
    from django.utils import timezone

    from apps.bookings.models import Booking

    S = Booking.Status
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    jobs = Booking.objects.filter(fundi=profile)
    done = jobs.filter(status__in=[S.COMPLETED, S.CLOSED])
    amount = Sum("final_price_tzs")
    counts = jobs.aggregate(
        requested=Count("id", filter=Q(status=S.REQUESTED)),
        active=Count("id", filter=Q(status__in=[S.ACCEPTED, S.IN_PROGRESS])),
        total=Count("id"),
        answered=Count("id", filter=Q(responded_at__isnull=False)),
        accepted=Count("id", filter=Q(status__in=[S.ACCEPTED, S.IN_PROGRESS, S.COMPLETED, S.CLOSED, S.DISPUTED])),
    )
    six_months_ago = (month_start - timedelta(days=150)).replace(day=1)
    by_month = {
        row["month"].strftime("%Y-%m"): row
        for row in done.filter(completed_at__gte=six_months_ago)
        .annotate(month=TruncMonth("completed_at"))
        .values("month")
        .annotate(jobs=Count("id"), earnings=amount)
    }
    months = []
    cursor = six_months_ago
    while cursor <= month_start:
        key = cursor.strftime("%Y-%m")
        row = by_month.get(key, {})
        months.append({"month": key, "jobs": row.get("jobs", 0), "earnings_tzs": row.get("earnings") or 0})
        cursor = (cursor + timedelta(days=32)).replace(day=1)

    return {
        "profile_views": profile.profile_views,
        "saved_by": profile.favorited_by.count(),
        "rating_avg": float(profile.rating_avg),
        "rating_count": profile.rating_count,
        "completed_jobs": profile.completed_jobs_count,
        "avg_response_minutes": profile.avg_response_minutes,
        "requests_waiting": counts["requested"],
        "jobs_active": counts["active"],
        "acceptance_rate": round(counts["accepted"] / counts["answered"], 2) if counts["answered"] else None,
        "earnings_this_month_tzs": done.filter(completed_at__gte=month_start).aggregate(v=amount)["v"] or 0,
        "earnings_total_tzs": done.aggregate(v=amount)["v"] or 0,
        "months": months,
    }
