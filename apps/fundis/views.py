from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import IntegrityError
from django.db.models import F, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.geo import make_point

from . import services
from .models import FavoriteFundi, FundiProfile, FundiService, WorkPhoto
from .permissions import HasFundiProfile
from .serializers import (
    FundiProfileSerializer,
    FundiSearchSerializer,
    FundiServiceSerializer,
    MyWorkPhotoSerializer,
    PublicFundiDetailSerializer,
    PublicFundiSerializer,
    TopFundisSerializer,
)


class MyFundiProfileView(generics.RetrieveUpdateAPIView):
    """GET/PATCH the caller's fundi profile; POST creates it ("Become a Fundi")."""

    serializer_class = FundiProfileSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch"]
    # JSON for details, multipart for the cover photo.
    parser_classes = [JSONParser, MultiPartParser, FormParser]

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


class MyWorkPhotosViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The fundi's portfolio: upload (multipart `image`, `caption`, `category`), edit captions,
    delete, and POST /reorder/ {"ids": [...]} to set the order clients see."""

    serializer_class = MyWorkPhotoSerializer
    permission_classes = [IsAuthenticated, HasFundiProfile]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        return WorkPhoto.objects.filter(fundi__user=self.request.user).select_related("category")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated and hasattr(self.request.user, "fundi_profile"):
            context["fundi"] = self.request.user.fundi_profile
        return context

    def perform_create(self, serializer):
        fundi = self.request.user.fundi_profile
        last = fundi.work_photos.order_by("-sort_order").values_list("sort_order", flat=True).first()
        serializer.save(fundi=fundi, sort_order=0 if last is None else last + 1)

    def perform_destroy(self, instance):
        instance.image.delete(save=False)
        instance.thumbnail.delete(save=False)
        instance.delete()

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        ids = [str(i) for i in request.data.get("ids", [])]
        photos = {str(p.pk): p for p in self.get_queryset()}
        if sorted(ids) != sorted(photos):
            raise ValidationError({"ids": "Send every photo id exactly once."})
        for order, pk in enumerate(ids):
            WorkPhoto.objects.filter(pk=pk).update(sort_order=order)
        return Response(self.get_serializer(self.get_queryset().order_by("sort_order"), many=True).data)


class MyFundiStatsView(APIView):
    """Numbers for the fundi dashboard."""

    permission_classes = [IsAuthenticated, HasFundiProfile]

    def get(self, request):
        return Response(services.stats(request.user.fundi_profile))


class _PublicFundiMixin:
    """Shared by public fundi endpoints: favourite flags and efficient loading."""

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        context["favorite_ids"] = (
            set(FavoriteFundi.objects.filter(user=user).values_list("fundi_id", flat=True))
            if user.is_authenticated
            else set()
        )
        return context

    @staticmethod
    def optimise(qs):
        return qs.select_related("user").prefetch_related(
            "services__category", Prefetch("work_photos", queryset=WorkPhoto.objects.order_by("sort_order", "-created_at"))
        )


class FundiSearchView(_PublicFundiMixin, generics.ListAPIView):
    """Verified fundis near a point, with filters and sorting.

    A fundi appears only if the client is within the fundi's own service radius
    *and* the fundi is within the client's search radius. Fundis switched to "busy"
    are still listed (marked unavailable) unless `available_now=true`.
    """

    serializer_class = PublicFundiSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        params = FundiSearchSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        point = make_point(data["lat"], data["lng"])
        qs = (
            FundiProfile.objects.bookable()
            .serving_point(point, radius_km=data.get("radius_km", settings.SEARCH_DEFAULT_RADIUS_KM))
            .with_score()
            .with_min_price()
        )
        if data.get("category"):
            qs = qs.offering(data["category"])
        if data.get("available_now"):
            qs = qs.filter(is_available=True)
        if data.get("min_rating"):
            qs = qs.filter(rating_avg__gte=data["min_rating"])
        if data.get("max_price") is not None:
            qs = qs.filter(min_price__lte=data["max_price"])
        if data.get("q"):
            # Free text: business name, area, or a service the fundi offers (either language).
            text = data["q"]
            offered = FundiService.objects.filter(is_active=True).filter(
                Q(category__name_en__icontains=text) | Q(category__name_sw__icontains=text)
                | Q(category__parent__name_en__icontains=text) | Q(category__parent__name_sw__icontains=text)
            )
            qs = qs.filter(
                Q(business_name__icontains=text) | Q(area_text__icontains=text) | Q(district__icontains=text)
                | Q(pk__in=offered.values("fundi_id"))
            )
        order = {
            "distance": ("-is_available", "distance", "-score"),
            "rating": ("-score", "-completed_jobs_count", "distance"),
            "jobs": ("-completed_jobs_count", "-score", "distance"),
            "price": (F("min_price").asc(nulls_last=True), "distance"),
        }[data["sort"]]
        return self.optimise(qs).order_by(*order)


class TopFundisView(_PublicFundiMixin, generics.ListAPIView):
    """Best-rated fundis (fair Bayesian score), near a point if one is given, else nationwide."""

    serializer_class = PublicFundiSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        params = TopFundisSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        qs = FundiProfile.objects.bookable().with_score().with_min_price().filter(rating_count__gt=0)
        if data.get("lat") is not None and data.get("lng") is not None:
            point = make_point(data["lat"], data["lng"])
            qs = qs.filter(base_location__dwithin=(point, D(km=data["radius_km"]))).annotate(
                distance=Distance("base_location", point)
            )
        if data.get("category"):
            qs = qs.offering(data["category"])
        return self.optimise(qs).order_by("-score", "-completed_jobs_count")[: data["limit"]]


class PublicFundiReviewsView(generics.ListAPIView):
    """Reviews for a fundi, newest first. Reviewers are shown by first name only."""

    permission_classes = [AllowAny]

    def get_serializer_class(self):
        from apps.bookings.serializers import PublicReviewSerializer

        return PublicReviewSerializer

    def get_queryset(self):
        from apps.bookings.models import Review

        fundi = get_object_or_404(FundiProfile.objects.bookable(), pk=self.kwargs["pk"])
        return Review.objects.filter(fundi=fundi).select_related("client", "booking__category")


class PublicFundiDetailView(_PublicFundiMixin, generics.RetrieveAPIView):
    serializer_class = PublicFundiDetailSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        qs = self.optimise(FundiProfile.objects.bookable().with_score())
        fundi = get_object_or_404(qs, pk=self.kwargs["pk"])
        if fundi.user_id != getattr(self.request.user, "pk", None):
            # Counted for the fundi's statistics; not shown publicly.
            FundiProfile.objects.filter(pk=fundi.pk).update(profile_views=F("profile_views") + 1)
        return fundi


class MyFavoritesView(_PublicFundiMixin, generics.ListAPIView):
    """GET: my saved fundis. POST {fundi_id}: save one."""

    serializer_class = PublicFundiSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        saved = FavoriteFundi.objects.filter(user=self.request.user, fundi=OuterRef("pk")).values("created_at")[:1]
        return self.optimise(
            FundiProfile.objects.bookable().with_score().annotate(saved_at=Subquery(saved)).filter(saved_at__isnull=False)
        ).order_by("-saved_at")  # most recently saved first

    def post(self, request):
        fundi = get_object_or_404(FundiProfile.objects.bookable(), pk=request.data.get("fundi_id"))
        FavoriteFundi.objects.get_or_create(user=request.user, fundi=fundi)
        return Response({"fundi_id": str(fundi.pk), "is_favorite": True}, status=status.HTTP_201_CREATED)


class MyFavoriteDetailView(APIView):
    """DELETE: remove a saved fundi."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        FavoriteFundi.objects.filter(user=request.user, fundi_id=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
