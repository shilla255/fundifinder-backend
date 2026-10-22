from django.db import transaction

from apps.accounts.models import User
from apps.fundis.models import FundiProfile

from .messages import render
from .models import Broadcast, Notification
from .push import push_to_users
from .sms import send_sms


def notify(user, kind: str, data: dict | None = None, sms: bool = False, **context) -> Notification:
    """Create an in-app notification in the user's language, push it to the user's phones
    once the surrounding transaction commits, and optionally send an SMS (only to verified
    numbers, and only once an SMS backend is configured)."""
    title, body = render(kind, user.preferred_language, **context)
    notification = Notification.objects.create(
        user=user, kind=kind, title=title, body=body, data=data or {}
    )
    payload = {"kind": kind, **(data or {})}
    transaction.on_commit(lambda: push_to_users([user], title, body, data=payload))
    if sms and user.phone_verified:
        send_sms(user.phone_number, body)
    return notification


def audience_users(audience: str):
    users = User.objects.filter(is_active=True, is_staff=False)
    fundi_ids = FundiProfile.objects.values("user_id")
    if audience == Broadcast.Audience.CLIENTS:
        return users.exclude(id__in=fundi_ids)
    if audience == Broadcast.Audience.FUNDIS:
        return users.filter(id__in=fundi_ids)
    if audience == Broadcast.Audience.VERIFIED_FUNDIS:
        return users.filter(id__in=fundi_ids, identity_status=User.IdentityStatus.VERIFIED)
    return users


def send_broadcast(broadcast: Broadcast) -> Broadcast:
    """Fan a broadcast out: an in-app notification for each person (in their language) plus a push."""
    users = list(audience_users(broadcast.audience))
    image_url = None
    data = {"kind": "broadcast", "broadcast": str(broadcast.id), **({"link": broadcast.link} if broadcast.link else {})}
    Notification.objects.bulk_create(
        [
            Notification(
                user=u, kind="broadcast", data=data, image=broadcast.image.name if broadcast.image else None,
                title=broadcast.title_sw if u.preferred_language == "sw" else broadcast.title_en,
                body=broadcast.body_sw if u.preferred_language == "sw" else broadcast.body_en,
            )
            for u in users
        ]
    )
    pushed = 0
    for lang, title, body in (("sw", broadcast.title_sw, broadcast.body_sw), ("en", broadcast.title_en, broadcast.body_en)):
        group = [u for u in users if (u.preferred_language == "sw") == (lang == "sw")]
        if group:
            image_url = image_url or _absolute(broadcast)
            pushed += push_to_users(group, title, body, image=image_url, data=data)
    broadcast.recipients, broadcast.pushed = len(users), pushed
    broadcast.save(update_fields=["recipients", "pushed", "updated_at"])
    return broadcast


def _absolute(broadcast: Broadcast) -> str | None:
    from django.conf import settings

    if not broadcast.image:
        return None
    url = broadcast.image.url
    return url if url.startswith("http") else f"{settings.PUBLIC_BASE_URL.rstrip('/')}{url}"
