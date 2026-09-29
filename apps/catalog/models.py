from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel


class ServiceCategory(BaseModel):
    """Two levels at most: a trade (Umeme / Electrical) and optional specialisms (Solar)."""

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    slug = models.SlugField(max_length=60, unique=True)
    name_en = models.CharField(max_length=80)
    name_sw = models.CharField(max_length=80)
    icon = models.CharField(max_length=50, blank=True, help_text="Icon name used by the apps.")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name_en"]
        verbose_name_plural = "service categories"

    def __str__(self):
        return f"{self.parent.name_en} › {self.name_en}" if self.parent_id else self.name_en

    def clean(self):
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({"parent": "A category cannot be its own parent."})
            if self.parent.parent_id:
                raise ValidationError({"parent": "Categories can only be two levels deep."})
            if self.pk and self.children.exists():
                raise ValidationError({"parent": "A category with subcategories must stay top-level."})
