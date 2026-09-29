from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.bookings import services
from apps.bookings.models import Booking
from apps.core.testing import FAR_AWAY, MWENGE, make_category, make_fundi, make_user
from apps.fundis import services as fundi_services
from apps.fundis.models import FundiProfile
from apps.notifications.models import Notification


class BookingFlowTests(APITestCase):
    def setUp(self):
        self.category = make_category()
        self.fundi = make_fundi(category=self.category)
        self.client_user = make_user()

    def _create(self, user=None, location=MWENGE, **overrides):
        self.client.force_authenticate(user or self.client_user)
        payload = {
            "fundi_id": str(self.fundi.id),
            "category": self.category.slug,
            "description": "Socket sparks when used",
            "latitude": location[0],
            "longitude": location[1],
            "job_address": "Mwenge, near the market",
            **overrides,
        }
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/v1/bookings/", payload, format="json")

    def _act(self, booking_id, action, user, **data):
        self.client.force_authenticate(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/v1/bookings/{booking_id}/{action}/", data, format="json")

    def test_full_happy_path_with_review(self):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.data)
        booking_id = response.data["id"]
        self.assertTrue(response.data["reference"].startswith("FF-"))
        # Before acceptance the client can't see the fundi's phone.
        self.assertNotIn("phone_number", response.data["fundi"])
        requested = Notification.objects.get(user=self.fundi.user, kind="booking.requested")
        self.assertIn(self.category.name_sw, requested.body)  # users default to Kiswahili

        fundi_user = self.fundi.user
        response = self._act(booking_id, "accept", fundi_user, quoted_price_tzs=25000)
        self.assertEqual(response.data["status"], "accepted")
        self.assertEqual(response.data["client"]["phone_number"], self.client_user.phone_number)
        self.assertTrue(Notification.objects.filter(user=self.client_user, kind="booking.accepted").exists())

        self.assertEqual(self._act(booking_id, "start", fundi_user).data["status"], "in_progress")
        response = self._act(booking_id, "complete", fundi_user, final_price_tzs=30000)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["payment_status"], "paid_cash")

        self.client.force_authenticate(self.client_user)
        response = self.client.post(
            f"/api/v1/bookings/{booking_id}/review/", {"rating": 4, "comment": "Good"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        booking = Booking.objects.get(pk=booking_id)
        self.assertEqual(booking.status, Booking.Status.CLOSED)
        self.fundi.refresh_from_db()
        self.assertEqual(self.fundi.rating_count, 1)
        self.assertEqual(float(self.fundi.rating_avg), 4.0)
        self.assertEqual(self.fundi.completed_jobs_count, 1)
        self.assertEqual(
            list(booking.events.values_list("to_status", flat=True)),
            ["requested", "accepted", "in_progress", "completed", "closed"],
        )

    def test_client_cannot_accept_and_fundi_cannot_confirm(self):
        booking_id = self._create().data["id"]
        self.assertEqual(self._act(booking_id, "accept", self.client_user).status_code, 400)
        self._act(booking_id, "accept", self.fundi.user)
        self._act(booking_id, "start", self.fundi.user)
        self._act(booking_id, "complete", self.fundi.user)
        self.assertEqual(self._act(booking_id, "confirm", self.fundi.user).status_code, 400)

    def test_strangers_cannot_see_or_act(self):
        booking_id = self._create().data["id"]
        stranger = make_user()
        self.client.force_authenticate(stranger)
        self.assertEqual(self.client.get(f"/api/v1/bookings/{booking_id}/").status_code, 404)
        self.assertEqual(self._act(booking_id, "cancel", stranger, note="x").status_code, 404)

    def test_cancel_requires_reason(self):
        booking_id = self._create().data["id"]
        self.assertEqual(self._act(booking_id, "cancel", self.client_user).status_code, 400)
        response = self._act(booking_id, "cancel", self.client_user, note="Fixed it myself")
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(response.data["cancelled_by"], "client")

    def test_cannot_book_self_unverified_or_outside_area(self):
        self.assertEqual(self._create(user=self.fundi.user).status_code, 400)
        self.assertEqual(self._create(location=FAR_AWAY).status_code, 400)
        other_category = make_category("plumbing")
        self.assertEqual(self._create(category=other_category.slug).status_code, 400)
        self.fundi.user.identity_status = "pending"
        self.fundi.user.save()
        self.assertEqual(self._create().status_code, 400)

    def test_needs_phone_number_and_limits_open_requests(self):
        no_phone = make_user(phone_number=None)
        self.assertEqual(self._create(user=no_phone).status_code, 400)

        self.assertEqual(self._create().status_code, 201)
        self.assertEqual(self._create().status_code, 400)  # already pending with this fundi
        for _ in range(2):
            other = make_fundi(category=self.category)
            self.assertEqual(self._create(fundi_id=str(other.id)).status_code, 201)
        another = make_fundi(category=self.category)
        self.assertEqual(self._create(fundi_id=str(another.id)).status_code, 400)

    def test_list_by_role(self):
        self._create()
        self.client.force_authenticate(self.fundi.user)
        self.assertEqual(len(self.client.get("/api/v1/bookings/?as=fundi").data["results"]), 1)
        self.assertEqual(len(self.client.get("/api/v1/bookings/").data["results"]), 0)

    def test_expiry_and_auto_close(self):
        booking_id = self._create().data["id"]
        Booking.objects.filter(pk=booking_id).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.process_due_bookings()["expired"], 1)
        self.assertEqual(Booking.objects.get(pk=booking_id).status, Booking.Status.EXPIRED)

        booking_id = self._create().data["id"]
        for action in ("accept", "start", "complete"):
            self._act(booking_id, action, self.fundi.user)
        Booking.objects.filter(pk=booking_id).update(completed_at=timezone.now() - timedelta(hours=49))
        self.assertEqual(services.process_due_bookings()["closed"], 1)
        self.assertEqual(Booking.objects.get(pk=booking_id).status, Booking.Status.CLOSED)

    def test_suspending_fundi_cancels_jobs_not_started(self):
        requested = self._create().data["id"]
        other_client = make_user()
        accepted = self._create(user=other_client).data["id"]
        self._act(accepted, "accept", self.fundi.user)
        admin = make_user(is_staff=True)
        fundi_services.suspend(self.fundi, reason="Complaints", actor=admin)
        self.assertEqual(Booking.objects.get(pk=requested).status, Booking.Status.CANCELLED)
        self.assertEqual(Booking.objects.get(pk=accepted).status, Booking.Status.CANCELLED)
        self.assertEqual(FundiProfile.objects.get(pk=self.fundi.pk).status, FundiProfile.Status.SUSPENDED)
