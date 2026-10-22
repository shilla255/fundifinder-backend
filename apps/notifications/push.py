"""Push delivery (Firebase Cloud Messaging, HTTP v1) behind a small interface, like sms.py.

Production: set PUSH_BACKEND=apps.notifications.push.FCMBackend and give the server a
Firebase service-account key, either FIREBASE_CREDENTIALS_FILE (path) or
FIREBASE_CREDENTIALS_JSON (the JSON itself). The key is a secret: keep it out of git."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class BasePushBackend:
    def send(self, token: str, title: str, body: str, image: str | None, data: dict) -> bool:
        """Returns False when the token is dead and should be forgotten."""
        raise NotImplementedError


class ConsolePushBackend(BasePushBackend):
    def send(self, token, title, body, image, data):
        logger.info("PUSH %s… | %s | %s | image=%s | %s", token[:12], title, body, image, data)
        return True


class FCMBackend(BasePushBackend):
    def __init__(self):
        from google.oauth2 import service_account

        if settings.FIREBASE_CREDENTIALS_JSON:
            info = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
            self._credentials = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
        else:
            self._credentials = service_account.Credentials.from_service_account_file(
                settings.FIREBASE_CREDENTIALS_FILE, scopes=[SCOPE]
            )
        self._project = settings.FIREBASE_PROJECT_ID or self._credentials.project_id

    def _auth_header(self):
        from google.auth.transport.requests import Request

        if not self._credentials.valid:
            self._credentials.refresh(Request())
        return {"Authorization": f"Bearer {self._credentials.token}"}

    def send(self, token, title, body, image, data):
        message = {
            "token": token,
            "notification": {"title": title, "body": body, **({"image": image} if image else {})},
            "data": {k: str(v) for k, v in data.items()},
            "android": {"priority": "HIGH"},
        }
        r = requests.post(
            f"https://fcm.googleapis.com/v1/projects/{self._project}/messages:send",
            json={"message": message}, headers=self._auth_header(), timeout=10,
        )
        if r.ok:
            return True
        if r.status_code in (400, 404) and any(
            m in r.text for m in ("UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND")
        ):
            return False
        logger.warning("FCM error %s: %s", r.status_code, r.text[:300])
        return True


def get_backend() -> BasePushBackend:
    return import_string(settings.PUSH_BACKEND)()


def push_to_users(users, title: str, body: str, image: str | None = None, data: dict | None = None) -> int:
    """Push one message to every registered device of `users`. Never raises: a push
    problem must not break the booking or the broadcast that caused it."""
    from .models import Device

    devices = list(Device.objects.filter(user__in=users, user__is_active=True))
    if not devices:
        return 0
    try:
        backend = get_backend()
    except Exception:
        logger.exception("Push backend is not configured")
        return 0

    def one(device):
        try:
            return device, backend.send(device.token, title, body, image, data or {})
        except Exception:
            logger.exception("Push failed")
            return device, True

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, devices))
    dead = [d.pk for d, ok in results if not ok]
    if dead:
        Device.objects.filter(pk__in=dead).delete()
    return len(results) - len(dead)
