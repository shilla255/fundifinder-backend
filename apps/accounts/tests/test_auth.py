from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import AuthIdentity, OTPChallenge, User
from apps.core.phone import normalize_phone
from apps.core.testing import make_user

GOOGLE_CLAIMS = {
    "sub": "google-sub-123",
    "email": "Asha@Example.com",
    "email_verified": True,
    "name": "Asha Mushi",
    "picture": "https://example.com/a.jpg",
}


@override_settings(GOOGLE_OAUTH_CLIENT_IDS=["web-client-id"])
class GoogleSignInTests(APITestCase):
    url = "/api/v1/auth/google/"

    def setUp(self):
        cache.clear()

    def _post(self, claims):
        with mock.patch(
            "apps.accounts.services.google_id_token.verify_oauth2_token", return_value=claims
        ):
            return self.client.post(self.url, {"id_token": "token"}, format="json")

    def test_first_sign_in_creates_user_and_identity(self):
        response = self._post(GOOGLE_CLAIMS)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["created"])
        self.assertIn("access", response.data)
        user = User.objects.get(email="asha@example.com")
        self.assertEqual(user.full_name, "Asha Mushi")
        self.assertTrue(AuthIdentity.objects.filter(user=user, subject="google-sub-123").exists())

    def test_second_sign_in_returns_same_user(self):
        self._post(GOOGLE_CLAIMS)
        response = self._post({**GOOGLE_CLAIMS, "email": "asha.new@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["created"])
        self.assertEqual(User.objects.count(), 1)

    def test_links_to_existing_account_with_same_email(self):
        existing = make_user(email="asha@example.com")
        response = self._post(GOOGLE_CLAIMS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["id"], str(existing.id))

    def test_unverified_google_email_is_refused(self):
        response = self._post({**GOOGLE_CLAIMS, "email_verified": False})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_allows_small_clock_skew(self):
        with mock.patch(
            "apps.accounts.services.google_id_token.verify_oauth2_token", return_value=GOOGLE_CLAIMS
        ) as verify:
            self.client.post(self.url, {"id_token": "token"}, format="json")
        self.assertEqual(verify.call_args.kwargs["clock_skew_in_seconds"], 300)

    def test_invalid_token_is_refused(self):
        with mock.patch(
            "apps.accounts.services.google_id_token.verify_oauth2_token",
            side_effect=ValueError("bad"),
        ):
            response = self.client.post(self.url, {"id_token": "x"}, format="json")
        self.assertEqual(response.status_code, 400)


@override_settings(PHONE_OTP_ENABLED=True, SMS_BACKEND="apps.notifications.sms.DisabledSMSBackend")
class PhoneOTPTests(APITestCase):
    phone = "+255712345678"

    def setUp(self):
        cache.clear()

    def _request_code(self, **extra):
        with mock.patch("apps.accounts.services.secrets.randbelow", return_value=123456):
            return self.client.post(
                "/api/v1/auth/otp/request/", {"phone_number": "0712 345 678", **extra}, format="json"
            )

    def test_login_with_otp_creates_verified_phone_user(self):
        self.assertEqual(self._request_code().status_code, 202)
        response = self.client.post(
            "/api/v1/auth/otp/verify/", {"phone_number": self.phone, "code": "123456"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(phone_number=self.phone)
        self.assertTrue(user.phone_verified)

    def test_wrong_code_counts_attempts_and_code_is_single_use(self):
        self._request_code()
        bad = self.client.post(
            "/api/v1/auth/otp/verify/", {"phone_number": self.phone, "code": "000000"}, format="json"
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(OTPChallenge.objects.get().attempts, 1)
        ok = self.client.post(
            "/api/v1/auth/otp/verify/", {"phone_number": self.phone, "code": "123456"}, format="json"
        )
        self.assertEqual(ok.status_code, 201)
        again = self.client.post(
            "/api/v1/auth/otp/verify/", {"phone_number": self.phone, "code": "123456"}, format="json"
        )
        self.assertEqual(again.status_code, 400)

    def test_verify_phone_claims_number_from_unverified_accounts(self):
        squatter = make_user(phone_number=self.phone)
        owner = make_user(phone_number=None)
        self.client.force_authenticate(owner)
        self._request_code(purpose="verify_phone")
        response = self.client.post(
            "/api/v1/auth/otp/verify/",
            {"phone_number": self.phone, "code": "123456", "purpose": "verify_phone"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        owner.refresh_from_db()
        squatter.refresh_from_db()
        self.assertTrue(owner.phone_verified)
        self.assertIsNone(squatter.phone_number)

    @override_settings(PHONE_OTP_ENABLED=False)
    def test_disabled_until_sms_gateway_exists(self):
        self.assertEqual(self._request_code().status_code, 400)


class MeTests(APITestCase):
    def test_cannot_overwrite_verified_phone_by_patch(self):
        user = make_user()
        User.objects.filter(pk=user.pk).update(phone_verified_at="2026-01-01T00:00Z")
        user.refresh_from_db()
        self.client.force_authenticate(user)
        response = self.client.patch("/api/v1/me/", {"phone_number": "0754123456"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_phone_is_normalized(self):
        user = make_user(phone_number=None)
        self.client.force_authenticate(user)
        response = self.client.patch("/api/v1/me/", {"phone_number": "0754 123 456"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["phone_number"], "+255754123456")
        self.assertFalse(response.data["phone_verified"])


class PhoneNormalizationTests(APITestCase):
    def test_formats(self):
        for raw in ["0712345678", "+255712345678", "255712345678", "0712 345 678"]:
            self.assertEqual(normalize_phone(raw), "+255712345678")


FIREBASE_CLAIMS = {
    "iss": "https://securetoken.google.com/fundi-test",
    "aud": "fundi-test",
    "sub": "firebase-uid-1",
    "phone_number": "+255712345678",
}


@override_settings(FIREBASE_PROJECT_ID="fundi-test")
class FirebaseSignInTests(APITestCase):
    url = "/api/v1/auth/firebase/"

    def setUp(self):
        cache.clear()

    def _post(self, claims, **data):
        with mock.patch(
            "apps.accounts.services.google_id_token.verify_firebase_token", return_value=claims
        ) as verify:
            response = self.client.post(self.url, {"id_token": "token", **data}, format="json")
        return response, verify

    def test_signs_up_with_verified_phone(self):
        response, verify = self._post(FIREBASE_CLAIMS)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(verify.call_args.kwargs["audience"], "fundi-test")
        user = User.objects.get(phone_number="+255712345678")
        self.assertTrue(user.phone_verified)
        self.assertIn("access", response.data)

    def test_second_sign_in_returns_same_user(self):
        self._post(FIREBASE_CLAIMS)
        response, _ = self._post(FIREBASE_CLAIMS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_rejects_token_from_another_project(self):
        response, _ = self._post({**FIREBASE_CLAIMS, "iss": "https://securetoken.google.com/other"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_token_without_phone(self):
        claims = {k: v for k, v in FIREBASE_CLAIMS.items() if k != "phone_number"}
        response, _ = self._post(claims)
        self.assertEqual(response.status_code, 400)

    def test_verify_phone_for_google_user(self):
        user = make_user(phone_number=None)
        self.client.force_authenticate(user)
        response, _ = self._post(FIREBASE_CLAIMS, purpose="verify_phone")
        self.assertEqual(response.status_code, 200, response.data)
        user.refresh_from_db()
        self.assertEqual(user.phone_number, "+255712345678")
        self.assertTrue(user.phone_verified)

    @override_settings(FIREBASE_PROJECT_ID="")
    def test_not_configured(self):
        response, _ = self._post(FIREBASE_CLAIMS)
        self.assertEqual(response.status_code, 400)
