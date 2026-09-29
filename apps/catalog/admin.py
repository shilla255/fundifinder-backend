from django.contrib import admin

from .models import ServiceCategory


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ["__str__", "slug", "name_sw", "is_active", "sort_order"]
    list_filter = ["is_active", "parent"]
    list_editable = ["is_active", "sort_order"]
    search_fields = ["name_en", "name_sw", "slug"]
    prepopulated_fields = {"slug": ["name_en"]}
