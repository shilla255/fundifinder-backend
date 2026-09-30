from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.core.testing import image_file, make_fundi, make_user
from apps.fundis.models import FundiProfile
from apps.staff.models import StaffAction
from apps.verification.models import IdentityVerification as IV

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "private": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STORAGES)
class StaffConsoleTests(APITestCase):
    def setUp(self):
        self.staff = make_user(is_staff=True, full_name="Admin Asha")
        self.fundi_user = make_user(full_name="Juma Hassan")
        self.fundi = make_fundi(self.fundi_user)
        self.client_user = make_user(full_name="Peter Client")

    def _submit(self):
        self.client.force_authenticate(self.fundi_user)
        self.client.post(
            "/api/v1/verification/",
            {
                "document_type": "nida", "document_number": "19900115-12345-00001-23", "full_name": "Juma Hassan",
                "date_of_birth": "1990-01-15", "id_front_image": image_file("f.jpg"), "selfie_image": image_file("s.jpg"),
            },
            format="multipart",
        )
        return IV.objects.get()

    def _booking(self, status="requested"):
        return Booking.objects.create(
            client=self.client_user, fundi=self.fundi, category=self.fundi.services.first().category,
            description="Socket sparks", job_location=self.fundi.base_location, job_address="Sinza", status=status,
        )

    def test_non_staff_are_refused(self):
        self.client.force_authenticate(self.client_user)
        for url in ["/api/v1/admin/overview/", "/api/v1/admin/verifications/", "/api/v1/admin/users/"]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/v1/admin/overview/").status_code, 401)

    def test_overview(self):
        self._submit()
        self._booking(status="disputed")
        self.client.force_authenticate(self.staff)
        data = self.client.get("/api/v1/admin/overview/").data
        self.assertEqual(data["pending_verifications"], 1)
        self.assertEqual(data["open_disputes"], 1)
        self.assertEqual(len(data["daily"]), 14)
        self.assertEqual(data["daily"][-1]["new_bookings"], 1)

    def test_review_queue_images_and_approve(self):
        verification = self._submit()
        self.client.force_authenticate(self.staff)
        queue = self.client.get("/api/v1/admin/verifications/").data["results"]
        self.assertEqual(len(queue), 1)
        item = queue[0]
        self.assertTrue(item["portrait"])
        self.assertEqual(item["masked_number"], "19900115-•••••-•••••-23")
        self.assertTrue(item["dob_matches_nida"])
        self.assertEqual(item["fundi"]["id"], str(self.fundi.pk))
        image = self.client.get(item["images"]["selfie_image"])
        self.assertEqual(image.status_code, 200)
        self.assertIn("no-store", image["Cache-Control"])

        response = self.client.post(f"/api/v1/admin/verifications/{verification.pk}/recrop/", {"box": [0.1, 0.1, 0.5, 0.5]}, format="json")
        self.assertEqual(response.data["portrait_method"], "manual")
        response = self.client.post(f"/api/v1/admin/verifications/{verification.pk}/approve/")
        self.assertEqual(response.data["status"], "approved")
        self.fundi_user.refresh_from_db()
        self.assertTrue(self.fundi_user.is_identity_verified)
        self.assertEqual(
            list(StaffAction.objects.values_list("action", flat=True).order_by("created_at")),
            ["verification.recrop", "verification.approve"],
        )
        # Staff-only image stream
        self.client.force_authenticate(self.client_user)
        self.assertEqual(self.client.get(item["images"]["selfie_image"]).status_code, 403)

    def test_reject_needs_a_valid_reason(self):
        verification = self._submit()
        self.client.force_authenticate(self.staff)
        url = f"/api/v1/admin/verifications/{verification.pk}/reject/"
        self.assertEqual(self.client.post(url, {"reason": "because"}, format="json").status_code, 400)
        response = self.client.post(url, {"reason": "unreadable", "note": "Blurry"}, format="json")
        self.assertEqual(response.data["status"], "rejected")

    def test_suspend_reinstate_and_ban_fundi(self):
        booking = self._booking()
        self.client.force_authenticate(self.staff)
        base = f"/api/v1/admin/fundis/{self.fundi.pk}"
        self.assertEqual(self.client.post(f"{base}/suspend/", {}, format="json").status_code, 400)  # reason required
        response = self.client.post(f"{base}/suspend/", {"reason": "Complaints"}, format="json")
        self.assertEqual(response.data["status"], "suspended")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(self.client.post(f"{base}/reinstate/", {}, format="json").data["status"], "active")
        self.assertEqual(self.client.post(f"{base}/ban/", {"reason": "Fraud"}, format="json").data["status"], "banned")
        self.assertEqual(self.client.post(f"{base}/reinstate/", {}, format="json").status_code, 400)
        listing = self.client.get("/api/v1/admin/fundis/?status=banned").data["results"]
        self.assertEqual([f["id"] for f in listing], [str(self.fundi.pk)])

    def test_resolve_dispute(self):
        booking = self._booking(status="disputed")
        self.client.force_authenticate(self.staff)
        url = f"/api/v1/admin/bookings/{booking.pk}/resolve_close/"
        self.assertEqual(self.client.post(url, {"note": ""}, format="json").status_code, 400)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"note": "Fundi finished; client paid."}, format="json")
        self.assertEqual(response.data["status"], "closed")
        self.assertEqual(response.data["events"][-1]["actor_role"], "admin")
        self.fundi.refresh_from_db()
        self.assertEqual(self.fundi.completed_jobs_count, 1)
        self.assertEqual(self.client_user.notifications.filter(kind="booking.resolved").count(), 1)

    def test_deactivate_user_and_filters(self):
        self._booking()
        self.client.force_authenticate(self.staff)
        clients = self.client.get("/api/v1/admin/users/?role=client").data["results"]
        self.assertIn(str(self.client_user.pk), [u["id"] for u in clients])
        self.assertNotIn(str(self.fundi_user.pk), [u["id"] for u in clients])

        response = self.client.post(f"/api/v1/admin/users/{self.client_user.pk}/deactivate/", {"reason": "Spam"}, format="json")
        self.assertFalse(response.data["is_active"])
        self.assertEqual(Booking.objects.get().status, "cancelled")
        self.assertEqual(self.client.post(f"/api/v1/admin/users/{self.staff.pk}/deactivate/", {"reason": "x"}, format="json").status_code, 400)

        fundi_response = self.client.post(f"/api/v1/admin/users/{self.fundi_user.pk}/deactivate/", {"reason": "Spam"}, format="json")
        self.assertFalse(fundi_response.data["is_active"])
        self.fundi.refresh_from_db()
        self.assertEqual(self.fundi.status, FundiProfile.Status.SUSPENDED)

    def test_me_reports_staff_flag(self):
        self.client.force_authenticate(self.staff)
        self.assertTrue(self.client.get("/api/v1/me/").data["is_staff"])
        self.client.force_authenticate(self.client_user)
        self.assertFalse(self.client.get("/api/v1/me/").data["is_staff"])
