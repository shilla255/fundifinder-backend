from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Notification(BaseModel):
    """In-app notification. Push (FCM) and SMS delivery hang off the same record later."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=50, db_index=True)
    title = models.CharField(max_length=120)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    image = models.ImageField(upload_to="notifications/", null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return f"{self.kind} → {self.user}"


class Device(BaseModel):
    """A phone that can receive push notifications (FCM registration token)."""

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    token = models.CharField(max_length=300, unique=True)
    platform = models.CharField(max_length=10, choices=Platform.choices, default=Platform.ANDROID)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.platform} · {self.user}"


class Broadcast(BaseModel):
    """A message staff send to a whole audience, in both languages, optionally with a picture."""

    class Audience(models.TextChoices):
        ALL = "all", "Everyone"
        CLIENTS = "clients", "Clients"
        FUNDIS = "fundis", "All fundis"
        VERIFIED_FUNDIS = "verified_fundis", "Verified fundis"

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    audience = models.CharField(max_length=20, choices=Audience.choices)
    title_sw = models.CharField(max_length=120)
    title_en = models.CharField(max_length=120)
    body_sw = models.TextField()
    body_en = models.TextField()
    image = models.ImageField(upload_to="broadcasts/", null=True, blank=True)
    link = models.CharField(max_length=120, blank=True, help_text="In-app route to open, e.g. /pro/verify")
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    recipients = models.PositiveIntegerField(default=0)
    pushed = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title_en} → {self.audience}"
