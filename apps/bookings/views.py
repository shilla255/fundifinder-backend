import random

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, mixins, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import services
from .models import Booking, Review
from .serializers import (
    ActionSerializer,
    BookingCreateSerializer,
    BookingSerializer,
    FeaturedReviewSerializer,
    ReviewSerializer,
)

# Actions whose note is required (the other side deserves a reason).
NOTE_REQUIRED = {"cancel", "dispute"}


class BookingViewSet(
    mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    list:   ?as=client (default) for jobs I requested, ?as=fundi for jobs sent to me.
            Optional ?status=requested,accepted
    create: request a specific fundi.
    """

    serializer_class = BookingSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Booking.objects.select_related("fundi__user", "client", "category", "review")
        if self.action == "list":
            if self.request.query_params.get("as") == "fundi":
                qs = qs.filter(fundi__user=user)
            else:
                qs = qs.filter(client=user)
            statuses = self.request.query_params.get("status")
            if statuses:
                qs = qs.filter(status__in=statuses.split(","))
            return qs
        return qs.filter(Q(client=user) | Q(fundi__user=user))

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            booking = services.create_booking(client=request.user, **serializer.validated_data)
        except services.BookingError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(
            self.get_serializer(booking).data, status=status.HTTP_201_CREATED
        )

    def _transition(self, request, action_name):
        booking = self.get_object()
        serializer = ActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        note = data.pop("note", "")
        if action_name in NOTE_REQUIRED and not note:
            raise ValidationError({"note": "Please give a reason."})
        try:
            booking = services.transition(
                booking,
                action_name,
                actor=request.user,
                role=services.role_of(booking, request.user),
                note=note,
                **data,
            )
        except services.BookingError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(booking).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._transition(request, "accept")

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._transition(request, "decline")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._transition(request, "start")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._transition(request, "complete")

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._transition(request, "confirm")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition(request, "cancel")

    @action(detail=True, methods=["post"])
    def dispute(self, request, pk=None):
        return self._transition(request, "dispute")

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        booking = self.get_object()
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = services.create_review(booking, request.user, **serializer.validated_data)
        except services.BookingError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class FeaturedReviewsView(generics.ListAPIView):
    """Good, written reviews from different service categories for the home screen.

    One per top-level category where possible, shuffled once a day so the page
    stays fresh without changing on every refresh.
    """

    serializer_class = FeaturedReviewSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        from apps.fundis.models import FundiProfile

        try:
            limit = max(1, min(int(self.request.query_params.get("limit", 6)), 20))
        except ValueError:
            limit = 6
        candidates = list(
            Review.objects.filter(rating__gte=4, fundi__in=FundiProfile.objects.bookable())
            .exclude(comment="")
            .select_related("client", "fundi__user", "booking__category__parent")
            .order_by("-created_at")[:200]
        )
        random.Random(timezone.localdate().toordinal()).shuffle(candidates)
        picked, seen = [], set()
        for review in candidates:  # first pass: one per category
            category = review.booking.category
            top = category.parent_id or category.pk
            if top not in seen:
                seen.add(top)
                picked.append(review)
        picked += [r for r in candidates if r not in picked]  # then fill up
        return picked[:limit]
