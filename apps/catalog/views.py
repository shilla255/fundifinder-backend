from django.db.models import Prefetch
from rest_framework import generics
from rest_framework.permissions import AllowAny

from .models import ServiceCategory
from .serializers import CategorySerializer


class CategoryListView(generics.ListAPIView):
    """Active top-level categories with their active subcategories."""

    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        return ServiceCategory.objects.filter(parent__isnull=True, is_active=True).prefetch_related(
            Prefetch("children", queryset=ServiceCategory.objects.filter(is_active=True))
        )
