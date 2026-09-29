from .messages import render
from .models import Notification
from .sms import send_sms


def notify(user, kind: str, data: dict | None = None, sms: bool = False, **context) -> Notification:
    """Create an in-app notification in the user's language; optionally also send an SMS
    (only to verified numbers, and only once an SMS backend is configured)."""
    title, body = render(kind, user.preferred_language, **context)
    notification = Notification.objects.create(
        user=user, kind=kind, title=title, body=body, data=data or {}
    )
    if sms and user.phone_verified:
        send_sms(user.phone_number, body)
    return notification
