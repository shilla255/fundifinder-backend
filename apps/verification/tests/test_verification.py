from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.core.testing import image_file, make_fundi, make_user
from apps.fundis.models import FundiProfile
from apps.notifications.models import Notification
from apps.verification import services
from apps.verification.models import IdentityVerification as IV

NIDA = "19900115-12345-00001-23"
NIDA_DIGITS = "19900115123450000123"


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "private": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class VerificationTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.admin = make_user(is_staff=True)

    def _payload(self, **overrides):
        return {
            "nida_number": NIDA,
            "full_name": "Juma Hassan",
            "date_of_birth": "1990-01-15",
            "id_front_image": image_file("front.jpg"),
            "selfie_image": image_file("selfie.jpg"),
            **overrides,
        }

    def _submit(self, user=None):
        self.client.force_authenticate(user or self.user)
        return self.client.post("/api/v1/verification/", self._payload(), format="multipart")

    def test_submit_stores_encrypted_nida_and_sets_pending(self):
        response = self._submit()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["nida_last4"], "0123")
        self.assertNotIn("nida_number", response.data)
        verification = IV.objects.get()
        self.assertNotIn(NIDA_DIGITS, verification.nida_number_encrypted)
        self.assertEqual(verification.nida_number, NIDA_DIGITS)
        self.assertTrue(verification.dob_matches_nida)
        self.user.refresh_from_db()
        self.assertEqual(self.user.identity_status, User.IdentityStatus.PENDING)

    def test_cannot_submit_twice_while_pending(self):
        self._submit()
        self.assertEqual(self._submit().status_code, 400)

    def test_rejects_bad_nida_number(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/v1/verification/", self._payload(nida_number="1234"), format="multipart"
        )
        self.assertEqual(response.status_code, 400)

    def test_approve_then_reverify_then_approve_again(self):
        self._submit()
        with self.captureOnCommitCallbacks(execute=True):
            services.approve(IV.objects.get(), self.admin)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_identity_verified)
        self.assertTrue(Notification.objects.filter(user=self.user, kind="verification.approved").exists())

        services.require_reverification(self.user, self.admin, "Name changed")
        self.user.refresh_from_db()
        self.assertEqual(self.user.identity_status, User.IdentityStatus.REVERIFICATION_REQUIRED)

        self._submit()
        services.approve(IV.objects.get(status=IV.Status.PENDING), self.admin)
        statuses = sorted(IV.objects.values_list("status", flat=True))
        self.assertEqual(statuses, ["approved", "superseded"])

    def test_reject_allows_resubmission(self):
        self._submit()
        services.reject(IV.objects.get(), self.admin, IV.RejectionReason.UNREADABLE)
        self.user.refresh_from_db()
        self.assertEqual(self.user.identity_status, User.IdentityStatus.REJECTED)
        self.assertEqual(self._submit().status_code, 201)
        self.assertEqual(IV.objects.count(), 2)

    def test_same_nida_on_second_account_is_flagged_and_cannot_be_approved(self):
        self._submit()
        services.approve(IV.objects.get(), self.admin)
        other = make_user()
        self._submit(other)
        duplicate = IV.objects.get(user=other)
        self.assertTrue(duplicate.is_duplicate_nida)
        with self.assertRaises(services.VerificationError):
            services.approve(duplicate, self.admin)

    def test_revoke_bans_fundi(self):
        fundi = make_fundi(self.user)
        services.revoke(self.user, self.admin, "Fake ID")
        fundi.refresh_from_db()
        self.assertEqual(fundi.status, FundiProfile.Status.BANNED)
        self.assertFalse(FundiProfile.objects.discoverable().filter(pk=fundi.pk).exists())

    def test_underage_is_refused(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/v1/verification/", self._payload(date_of_birth="2015-01-01"), format="multipart"
        )
        self.assertEqual(response.status_code, 400)

    def test_status_endpoint(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/v1/verification/")
        self.assertEqual(response.data["identity_status"], "unverified")
        self.assertIsNone(response.data["latest_submission"])

    def test_admin_review_page_and_private_image(self):
        self._submit()
        verification = IV.objects.get()
        superuser = User.objects.create_superuser("admin@example.com", "pw-123456789")
        self.client.force_login(superuser)
        page = self.client.get(f"/admin/verification/identityverification/{verification.pk}/change/")
        self.assertContains(page, "Approve identity")
        image = self.client.get(
            f"/admin/verification/identityverification/{verification.pk}/image/selfie_image/"
        )
        self.assertEqual(image.status_code, 200)
        self.assertIn("no-store", image["Cache-Control"])

        self.client.logout()
        self.client.force_login(self.user)
        image = self.client.get(
            f"/admin/verification/identityverification/{verification.pk}/image/selfie_image/"
        )
        self.assertEqual(image.status_code, 302)  # redirected to admin login

        self.client.force_login(superuser)
        response = self.client.post(
            f"/admin/verification/identityverification/{verification.pk}/change/",
            {"rejection_reason": "", "review_note": "", "_approve": "1",
             "events-TOTAL_FORMS": "1", "events-INITIAL_FORMS": "1",
             "events-MIN_NUM_FORMS": "0", "events-MAX_NUM_FORMS": "1000",
             "events-0-id": str(verification.events.get().pk), "events-0-verification": str(verification.pk)},
        )
        self.assertEqual(response.status_code, 302)
        verification.refresh_from_db()
        self.assertEqual(verification.status, IV.Status.APPROVED)
