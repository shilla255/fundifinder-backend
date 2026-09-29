import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.sms import send_sms

from .models import AuthIdentity, OTPChallenge, User


class AuthError(Exception):
    pass


def issue_tokens(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


# --- Google Sign-In -------------------------------------------------------


def verify_google_id_token(token: str) -> dict:
    """Validate a Google ID token (signature, expiry, issuer, audience) and return its claims."""
    client_ids = settings.GOOGLE_OAUTH_CLIENT_IDS
    if not client_ids:
        raise AuthError("Google sign-in is not configured.")
    try:
        return google_id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=client_ids
        )
    except ValueError as exc:
        raise AuthError("Invalid Google token.") from exc


@transaction.atomic
def sign_in_with_google(token: str) -> tuple[User, bool]:
    """Return (user, created). Links to an existing account with the same verified email."""
    claims = verify_google_id_token(token)
    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified"):
        raise AuthError("Your Google account email is not verified.")

    created = False
    identity = (
        AuthIdentity.objects.select_related("user")
        .filter(provider=AuthIdentity.Provider.GOOGLE, subject=claims["sub"])
        .first()
    )
    if identity:
        user = identity.user
        identity.email = email
        identity.last_used_at = timezone.now()
        identity.save(update_fields=["email", "last_used_at", "updated_at"])
    else:
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(
                email=email,
                full_name=claims.get("name", ""),
                avatar_url=claims.get("picture", ""),
            )
            created = True
        AuthIdentity.objects.create(
            user=user, provider=AuthIdentity.Provider.GOOGLE, subject=claims["sub"], email=email
        )

    if not user.is_active:
        raise AuthError("This account is disabled.")
    return user, created


# --- Phone OTP ------------------------------------------------------------


def _hash_code(phone_number: str, code: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{phone_number}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def request_otp(phone_number: str, purpose: str, user: User | None = None, ip_address=None):
    if not settings.PHONE_OTP_ENABLED:
        raise AuthError("Phone sign-in is not available yet. Please continue with Google.")

    if purpose == OTPChallenge.Purpose.VERIFY_PHONE:
        taken = (
            User.objects.filter(phone_number=phone_number, phone_verified_at__isnull=False)
            .exclude(pk=user.pk)
            .exists()
        )
        if taken:
            raise AuthError("This phone number is already registered to another account.")

    # SMS costs money and OTP endpoints attract SMS-pumping fraud: cap per number.
    recent = OTPChallenge.objects.filter(
        phone_number=phone_number, created_at__gte=timezone.now() - timedelta(hours=1)
    ).count()
    if recent >= settings.OTP_MAX_PER_PHONE_PER_HOUR:
        raise AuthError("Too many codes requested. Please try again later.")

    code = f"{secrets.randbelow(10**6):06d}"
    OTPChallenge.objects.create(
        phone_number=phone_number,
        purpose=purpose,
        user=user,
        code_hash=_hash_code(phone_number, code),
        expires_at=timezone.now() + timedelta(minutes=settings.OTP_TTL_MINUTES),
        ip_address=ip_address,
    )
    send_sms(
        phone_number,
        f"FundiFinder: nambari yako ya uthibitisho ni {code}. "
        f"Inaisha baada ya dakika {settings.OTP_TTL_MINUTES}.",
    )


def _check_otp(phone_number: str, code: str, purpose: str, user: User | None) -> OTPChallenge:
    """Consume a matching challenge. Failed attempts are committed even though we raise."""
    error = None
    with transaction.atomic():
        challenges = OTPChallenge.objects.select_for_update().filter(
            phone_number=phone_number,
            purpose=purpose,
            consumed_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        if user is not None:
            challenges = challenges.filter(user=user)
        challenge = challenges.order_by("-created_at").first()

        if challenge is None:
            error = "Code expired or not found. Request a new one."
        elif challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
            error = "Too many attempts. Request a new code."
        elif not hmac.compare_digest(challenge.code_hash, _hash_code(phone_number, code)):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts", "updated_at"])
            error = "Incorrect code."
        else:
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at", "updated_at"])
    if error:
        raise AuthError(error)
    return challenge


def _release_unverified_copies(phone_number: str, owner: User):
    """Once someone proves they own a number, drop it from accounts that only typed it in."""
    User.objects.filter(
        phone_number=phone_number, phone_verified_at__isnull=True, email__isnull=False
    ).exclude(pk=owner.pk).update(phone_number=None)


def sign_in_with_otp(phone_number: str, code: str) -> tuple[User, bool]:
    _check_otp(phone_number, code, OTPChallenge.Purpose.LOGIN, user=None)
    with transaction.atomic():
        user = User.objects.filter(
            phone_number=phone_number, phone_verified_at__isnull=False
        ).first()
        created = user is None
        if created:
            user = User.objects.create_user(
                phone_number=phone_number, phone_verified_at=timezone.now()
            )
            _release_unverified_copies(phone_number, user)
    if not user.is_active:
        raise AuthError("This account is disabled.")
    return user, created


def verify_phone_for_user(user: User, phone_number: str, code: str) -> User:
    _check_otp(phone_number, code, OTPChallenge.Purpose.VERIFY_PHONE, user=user)
    with transaction.atomic():
        taken = (
            User.objects.filter(phone_number=phone_number, phone_verified_at__isnull=False)
            .exclude(pk=user.pk)
            .exists()
        )
        if taken:
            raise AuthError("This phone number is already registered to another account.")
        user.phone_number = phone_number
        user.phone_verified_at = timezone.now()
        user.save(update_fields=["phone_number", "phone_verified_at"])
        _release_unverified_copies(phone_number, user)
    return user
