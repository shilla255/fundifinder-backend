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
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return f"{self.kind} → {self.user}"
