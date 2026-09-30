from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class StaffAction(BaseModel):
    """Who did what, to what, and why — every decision taken in the staff console."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=40, db_index=True)  # e.g. "verification.approve", "fundi.suspend"
    target_type = models.CharField(max_length=30)  # "verification" | "fundi" | "user" | "booking"
    target_id = models.CharField(max_length=64, db_index=True)
    target_label = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.actor} {self.action} {self.target_label or self.target_id}"
