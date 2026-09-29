from django.conf import settings
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.geo import make_point

from . import services
from .models import FundiProfile, FundiService
from .permissions import HasFundiProfile
from .serializers import (
    FundiProfileSerializer,
    FundiSearchSerializer,
    FundiServiceSerializer,
    PublicFundiSerializer,
)


class MyFundiProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH the caller's fundi profile; POST creates it ("Become a Fundi")."""

    serializer_class = FundiProfileSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch"]

    def get_object(self):
        profile = FundiProfile.objects.filter(user=self.request.user).first()
        if profile is None:
            raise NotFound("You don't have a fundi profile yet.")
        return profile

    def post(self, request):
        if FundiProfile.objects.filter(user=request.user).exists():
            raise ValidationError({"detail": "You already have a fundi profile."})
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(user=request.user)
        except IntegrityError as exc:
            raise ValidationError({"detail": "You already have a fundi profile."}) from exc
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class _ProfileActionView(APIView):
    permission_classes = [IsAuthenticated, HasFundiProfile]
    action_func = None

    def post(self, request):
        try:
            profile = type(self).action_func(request.user.fundi_profile)
        except services.FundiError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(FundiProfileSerializer(profile, context={"request": request}).data)


class ActivateProfileView(_ProfileActionView):
    action_func = staticmethod(services.activate)


class PauseProfileView(_ProfileActionView):
    action_func = staticmethod(services.pause)


class MyServicesViewSet(viewsets.ModelViewSet):
    serializer_class = FundiServiceSerializer
    permission_classes = [IsAuthenticated, HasFundiProfile]
    pagination_class = None

    def get_queryset(self):
        return FundiService.objects.filter(fundi__user=self.request.user).select_related("category")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated and hasattr(self.request.user, "fundi_profile"):
            context["fundi"] = self.request.user.fundi_profile
        return context

    def perform_create(self, serializer):
        serializer.save(fundi=self.request.user.fundi_profile)


class FundiSearchView(generics.ListAPIView):
    """Verified, available fundis near a point, nearest first.

    A fundi appears only if the client is within the fundi's own service radius
    *and* the fundi is within the client's search radius.
    """

    serializer_class = PublicFundiSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        params = FundiSearchSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        point = make_point(data["lat"], data["lng"])
        qs = FundiProfile.objects.discoverable().serving_point(
            point, radius_km=data.get("radius_km", settings.SEARCH_DEFAULT_RADIUS_KM)
        )
        if data.get("category"):
            qs = qs.offering(data["category"])
        return qs.select_related("user").prefetch_related("services__category").order_by(
            "distance", "-rating_avg"
        )


class PublicFundiReviewsView(generics.ListAPIView):
    """Reviews for a discoverable fundi, newest first. Reviewers are shown by first name only."""

    permission_classes = [AllowAny]

    def get_serializer_class(self):
        from apps.bookings.serializers import PublicReviewSerializer

        return PublicReviewSerializer

    def get_queryset(self):
        from apps.bookings.models import Review

        fundi = get_object_or_404(FundiProfile.objects.discoverable(), pk=self.kwargs["pk"])
        return Review.objects.filter(fundi=fundi).select_related("client", "booking__category")


class PublicFundiDetailView(generics.RetrieveAPIView):
    serializer_class = PublicFundiSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        qs = FundiProfile.objects.discoverable().select_related("user")
        return get_object_or_404(qs.prefetch_related("services__category"), pk=self.kwargs["pk"])
