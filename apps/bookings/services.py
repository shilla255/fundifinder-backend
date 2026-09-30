"""Booking lifecycle. Every status change goes through `transition()` so the rules,
the audit log and the notifications live in one place."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, F
from django.utils import timezone

from apps.fundis.models import FundiProfile, FundiService
from apps.notifications.services import notify

from .models import Booking, BookingEvent, Review

S = Booking.Status
P = Booking.Party

# action: (allowed from-statuses, to-status, who may do it)
TRANSITIONS = {
    "accept": ({S.REQUESTED}, S.ACCEPTED, {P.FUNDI}),
    "decline": ({S.REQUESTED}, S.DECLINED, {P.FUNDI}),
    "start": ({S.ACCEPTED}, S.IN_PROGRESS, {P.FUNDI}),
    "complete": ({S.IN_PROGRESS}, S.COMPLETED, {P.FUNDI}),
    "confirm": ({S.COMPLETED}, S.CLOSED, {P.CLIENT, P.SYSTEM}),
    "cancel": ({S.REQUESTED, S.ACCEPTED}, S.CANCELLED, {P.CLIENT, P.FUNDI, P.SYSTEM, P.ADMIN}),
    "dispute": ({S.IN_PROGRESS, S.COMPLETED}, S.DISPUTED, {P.CLIENT, P.FUNDI}),
    "expire": ({S.REQUESTED}, S.EXPIRED, {P.SYSTEM}),
}

# Who hears about each new status (the other party, or both for system actions).
NOTIFY_KIND = {
    S.ACCEPTED: "booking.accepted",
    S.DECLINED: "booking.declined",
    S.EXPIRED: "booking.expired",
    S.IN_PROGRESS: "booking.started",
    S.COMPLETED: "booking.completed",
    S.CANCELLED: "booking.cancelled",
    S.DISPUTED: "booking.disputed",
}


class BookingError(Exception):
    pass


def role_of(booking: Booking, user) -> str | None:
    if booking.client_id == user.pk:
        return P.CLIENT
    if booking.fundi.user_id == user.pk:
        return P.FUNDI
    return None


def _log(booking, from_status, actor, role, note=""):
    BookingEvent.objects.create(
        booking=booking,
        from_status=from_status,
        to_status=booking.status,
        actor=actor,
        actor_role=role,
        note=note,
    )


def _category_name(category, user) -> str:
    return category.name_sw if user.preferred_language == "sw" else category.name_en


def _notify(booking: Booking, role: str):
    kind = NOTIFY_KIND.get(booking.status)
    if not kind:
        return
    context = {
        "ref": booking.reference,
        "fundi": booking.fundi.business_name,
        "client": booking.client.full_name or "A client",
    }
    data = {"booking_id": str(booking.pk), "reference": booking.reference}
    recipients = []
    if role != P.CLIENT:
        recipients.append(booking.client)
    if role != P.FUNDI:
        recipients.append(booking.fundi.user)
    for user in recipients:
        notify(user, kind, data=data, category=_category_name(booking.category, user), **context)


@transaction.atomic
def create_booking(
    *, client, fundi: FundiProfile, category, description, job_location, job_address,
    landmark="", requested_for=None,
) -> Booking:
    if not client.phone_number:
        raise BookingError("Add a phone number to your profile so the fundi can reach you.")
    if fundi.user_id == client.pk:
        raise BookingError("You can't book yourself.")
    if not FundiProfile.objects.bookable().filter(pk=fundi.pk).exists():
        raise BookingError("This fundi is not taking bookings right now.")
    if not FundiService.objects.filter(
        fundi=fundi, category=category, is_active=True, category__is_active=True
    ).exists():
        raise BookingError("This fundi doesn't offer that service.")
    if not FundiProfile.objects.filter(pk=fundi.pk).serving_point(job_location).exists():
        raise BookingError("This location is outside the fundi's service area.")

    open_requests = Booking.objects.filter(client=client, status=S.REQUESTED)
    if open_requests.filter(fundi=fundi).exists():
        raise BookingError("You already have a pending request with this fundi.")
    if open_requests.count() >= settings.BOOKING_MAX_OPEN_REQUESTS:
        raise BookingError("You have too many pending requests. Wait for a reply or cancel one.")

    booking = Booking.objects.create(
        client=client,
        fundi=fundi,
        category=category,
        description=description,
        job_location=job_location,
        job_address=job_address,
        landmark=landmark,
        requested_for=requested_for,
        expires_at=timezone.now() + timedelta(minutes=settings.BOOKING_RESPONSE_MINUTES),
    )
    _log(booking, "", client, P.CLIENT)
    context = {
        "ref": booking.reference,
        "client": client.full_name or "A client",
        "category": _category_name(category, fundi.user),
    }
    transaction.on_commit(
        lambda: notify(
            fundi.user,
            "booking.requested",
            data={"booking_id": str(booking.pk), "reference": booking.reference},
            sms=True,
            **context,
        )
    )
    return booking


@transaction.atomic
def transition(booking: Booking, action: str, *, actor=None, role: str, note: str = "", **fields) -> Booking:
    if action not in TRANSITIONS:
        raise BookingError(f"Unknown action '{action}'.")
    allowed_from, to_status, roles = TRANSITIONS[action]

    # Lock the row so two taps (or a tap racing the expiry job) can't both win.
    booking = (
        Booking.objects.select_for_update(of=("self",))
        .select_related("fundi__user", "client", "category")
        .get(pk=booking.pk)
    )
    if role not in roles:
        raise BookingError(f"You can't {action} this booking.")
    if booking.status not in allowed_from:
        raise BookingError(
            f"Can't {action} a booking that is {booking.get_status_display().lower()}."
        )

    now = timezone.now()
    from_status = booking.status
    booking.status = to_status

    if action == "accept":
        booking.responded_at = now
        booking.quoted_price_tzs = fields.get("quoted_price_tzs", booking.quoted_price_tzs)
    elif action == "decline":
        booking.responded_at = now
    elif action == "start":
        booking.started_at = now
    elif action == "complete":
        booking.completed_at = now
        if fields.get("final_price_tzs") is not None:
            booking.final_price_tzs = fields["final_price_tzs"]
        # Marking a cash job complete means the fundi has been paid.
        booking.payment_status = Booking.PaymentStatus.PAID_CASH
    elif action == "confirm":
        booking.closed_at = now
        FundiProfile.objects.filter(pk=booking.fundi_id).update(
            completed_jobs_count=F("completed_jobs_count") + 1
        )
    elif action == "cancel":
        booking.cancelled_at = now
        booking.cancelled_by = role
        booking.cancellation_reason = note
    elif action == "dispute":
        booking.dispute_reason = note
        booking.payment_status = Booking.PaymentStatus.DISPUTED

    booking.save()
    _log(booking, from_status, actor, role, note)
    if action in ("accept", "decline"):
        _update_response_time(booking.fundi_id)
    transaction.on_commit(lambda: _notify(booking, role))
    return booking


def _update_response_time(fundi_id):
    """Average minutes the fundi takes to answer requests (last 20 answers) — shown as a badge."""
    recent = (
        Booking.objects.filter(fundi_id=fundi_id, responded_at__isnull=False)
        .order_by("-responded_at")
        .values_list("created_at", "responded_at")[:20]
    )
    minutes = [max((answered - asked).total_seconds() / 60, 0) for asked, answered in recent]
    if minutes:
        FundiProfile.objects.filter(pk=fundi_id).update(avg_response_minutes=round(sum(minutes) / len(minutes)))


def cancel_open_bookings_for_fundi(fundi: FundiProfile, reason: str, actor=None):
    """Used when a fundi is suspended/banned: cancel everything that hasn't started."""
    for booking in Booking.objects.filter(fundi=fundi, status__in=[S.REQUESTED, S.ACCEPTED]):
        transition(booking, "cancel", actor=actor, role=P.ADMIN if actor else P.SYSTEM, note=reason)


def process_due_bookings(now=None) -> dict:
    """Expire unanswered requests and close completed jobs the client never confirmed.
    Run every few minutes (cron / Cloud Scheduler → `manage.py process_bookings`)."""
    now = now or timezone.now()
    counts = {"expired": 0, "closed": 0}
    for booking in Booking.objects.filter(status=S.REQUESTED, expires_at__lte=now):
        try:
            transition(booking, "expire", role=P.SYSTEM)
            counts["expired"] += 1
        except BookingError:
            pass  # changed by someone else in the meantime
    cutoff = now - timedelta(hours=settings.BOOKING_AUTO_CLOSE_HOURS)
    for booking in Booking.objects.filter(status=S.COMPLETED, completed_at__lte=cutoff):
        try:
            transition(booking, "confirm", role=P.SYSTEM, note="Auto-closed")
            counts["closed"] += 1
        except BookingError:
            pass
    return counts


@transaction.atomic
def create_review(booking: Booking, client, rating: int, comment: str = "") -> Review:
    if booking.client_id != client.pk:
        raise BookingError("Only the client can review this job.")
    if booking.status not in (S.COMPLETED, S.CLOSED):
        raise BookingError("You can review a job once it is completed.")
    if Review.objects.filter(booking=booking).exists():
        raise BookingError("You already reviewed this job.")

    review = Review.objects.create(
        booking=booking, fundi=booking.fundi, client=client, rating=rating, comment=comment
    )
    if booking.status == S.COMPLETED:
        transition(booking, "confirm", actor=client, role=P.CLIENT, note="Confirmed with review")

    fundi = FundiProfile.objects.select_for_update().get(pk=booking.fundi_id)
    stats = Review.objects.filter(fundi=fundi).aggregate(avg=Avg("rating"), count=Count("id"))
    fundi.rating_avg = round(stats["avg"] or 0, 2)
    fundi.rating_count = stats["count"]
    fundi.save(update_fields=["rating_avg", "rating_count", "updated_at"])
    return review
