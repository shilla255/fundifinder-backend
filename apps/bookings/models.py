import secrets

from django.conf import settings
from django.contrib.gis.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q

from apps.core.models import BaseModel

# No 0/O/1/I/L so references are easy to read out over the phone.
REFERENCE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def generate_reference() -> str:
    return "FF-" + "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(6))


class Booking(BaseModel):
    """A client's request to a specific fundi. Paid in cash on completion for now."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed (awaiting client confirmation)"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"
        DISPUTED = "disputed", "Disputed"

    class Party(models.TextChoices):
        CLIENT = "client", "Client"
        FUNDI = "fundi", "Fundi"
        SYSTEM = "system", "System"
        ADMIN = "admin", "Admin"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID_CASH = "paid_cash", "Paid in cash"
        DISPUTED = "disputed", "Disputed"

    OPEN_STATUSES = (Status.REQUESTED, Status.ACCEPTED, Status.IN_PROGRESS)
    # Once accepted, both sides can see each other's phone number and the exact job location.
    CONTACT_VISIBLE_STATUSES = (Status.ACCEPTED, Status.IN_PROGRESS, Status.COMPLETED, Status.DISPUTED)

    reference = models.CharField(
        max_length=12, unique=True, default=generate_reference, editable=False
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="client_bookings"
    )
    fundi = models.ForeignKey(
        "fundis.FundiProfile", on_delete=models.PROTECT, related_name="bookings"
    )
    category = models.ForeignKey(
        "catalog.ServiceCategory", on_delete=models.PROTECT, related_name="bookings"
    )
    description = models.TextField()
    job_location = models.PointField(geography=True, srid=4326)
    job_address = models.CharField(max_length=255)
    landmark = models.CharField(max_length=255, blank=True)
    requested_for = models.DateTimeField(null=True, blank=True, help_text="Empty = as soon as possible.")

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.REQUESTED, db_index=True
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=10, choices=Party.choices, blank=True)
    cancellation_reason = models.TextField(blank=True)
    dispute_reason = models.TextField(blank=True)

    # Amounts in whole Tanzanian shillings.
    quoted_price_tzs = models.PositiveIntegerField(null=True, blank=True)
    final_price_tzs = models.PositiveIntegerField(null=True, blank=True)
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["fundi", "status"]),
        ]

    def __str__(self):
        return self.reference


class BookingEvent(BaseModel):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_role = models.CharField(max_length=10, choices=Booking.Party.choices)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.booking}: {self.from_status or '∅'} → {self.to_status}"


class Review(BaseModel):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="review")
    fundi = models.ForeignKey("fundis.FundiProfile", on_delete=models.CASCADE, related_name="reviews")
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_given"
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="rating_1_to_5"),
        ]

    def __str__(self):
        return f"{self.rating}★ for {self.fundi}"
