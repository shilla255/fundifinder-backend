"""Staff console API (/api/v1/admin/…). Every decision goes through the same services the
Django admin uses, and is written to `StaffAction`."""

from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.fundis import services as fundi_services
from apps.fundis.models import FundiProfile
from apps.notifications.services import notify
from apps.verification import services as verification_services
from apps.verification.models import IdentityVerification as IV

from .models import StaffAction
from .permissions import IsStaff
from .serializers import (
    BookingSerializer,
    BoxSerializer,
    FundiSerializer,
    NoteSerializer,
    ReasonSerializer,
    RejectSerializer,
    StaffActionSerializer,
    UserListSerializer,
    VerificationSerializer,
)

B = Booking.Status


def log(request, action, target_type, target_id, label="", note=""):
    StaffAction.objects.create(
        actor=request.user, action=action, target_type=target_type, target_id=str(target_id),
        target_label=str(label)[:200], note=note,
    )


class StaffView(APIView):
    permission_classes = [IsStaff]


# --- overview ------------------------------------------------------------------------


class OverviewView(StaffView):
    def get(self, request):
        now = timezone.now()
        since = (now - timedelta(days=13)).date()
        fundis = FundiProfile.objects.values("status").annotate(n=Count("id"))
        bookings = Booking.objects.values("status").annotate(n=Count("id"))
        new_users = dict(
            User.objects.filter(date_joined__date__gte=since)
            .annotate(day=TruncDate("date_joined")).values("day").annotate(n=Count("id")).values_list("day", "n")
        )
        new_bookings = dict(
            Booking.objects.filter(created_at__date__gte=since)
            .annotate(day=TruncDate("created_at")).values("day").annotate(n=Count("id")).values_list("day", "n")
        )
        days = [since + timedelta(days=i) for i in range(14)]
        return Response({
            "users": User.objects.count(),
            "clients": User.objects.filter(fundi_profile__isnull=True).count(),
            "fundis": {row["status"]: row["n"] for row in fundis},
            "fundis_live": FundiProfile.objects.discoverable().count(),
            "bookings": {row["status"]: row["n"] for row in bookings},
            "bookings_today": Booking.objects.filter(created_at__date=timezone.localdate()).count(),
            "pending_verifications": IV.objects.filter(status=IV.Status.PENDING).count(),
            "open_disputes": Booking.objects.filter(status=B.DISPUTED).count(),
            "daily": [
                {"date": d.isoformat(), "new_users": new_users.get(d, 0), "new_bookings": new_bookings.get(d, 0)}
                for d in days
            ],
            "recent_actions": StaffActionSerializer(StaffAction.objects.select_related("actor")[:8], many=True).data,
        })


# --- identity verifications ------------------------------------------------------------


class VerificationListView(generics.ListAPIView):
    """?status=pending (default) | approved | rejected | all, ?q= name / last digits / email / phone."""

    permission_classes = [IsStaff]
    serializer_class = VerificationSerializer

    def get_queryset(self):
        qs = IV.objects.select_related("user__fundi_profile", "reviewed_by")
        status = self.request.query_params.get("status", "pending")
        if status != "all":
            qs = qs.filter(status=status)
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q) | Q(document_last4__icontains=q)
                | Q(user__email__icontains=q) | Q(user__phone_number__icontains=q)
            )
        # Oldest first in the queue so nobody waits forever; newest first elsewhere.
        return qs.order_by("created_at" if status == "pending" else "-created_at")


class VerificationDetailView(generics.RetrieveAPIView):
    permission_classes = [IsStaff]
    serializer_class = VerificationSerializer
    queryset = IV.objects.select_related("user__fundi_profile", "reviewed_by")


class VerificationImageView(StaffView):
    """Streams a private document image to staff. Never cached, never public."""

    FIELDS = {"id_front_image", "id_back_image", "selfie_image"}

    def get(self, request, pk, field):
        if field not in self.FIELDS:
            raise Http404
        image = getattr(get_object_or_404(IV, pk=pk), field)
        if not image:
            raise Http404
        response = FileResponse(image.open("rb"))
        response["Cache-Control"] = "private, no-store"
        return response


class VerificationActionView(StaffView):
    """POST approve | reject {reason, note} | recrop {box}."""

    def post(self, request, pk, action):
        verification = get_object_or_404(IV.objects.select_related("user"), pk=pk)
        label = f"{verification.full_name} ({verification.get_document_type_display()})"
        try:
            if action == "approve":
                verification_services.approve(verification, request.user)
                log(request, "verification.approve", "verification", pk, label)
            elif action == "reject":
                data = RejectSerializer(data=request.data)
                data.is_valid(raise_exception=True)
                verification_services.reject(verification, request.user, data.validated_data["reason"], data.validated_data["note"])
                log(request, "verification.reject", "verification", pk, label, data.validated_data["reason"])
            elif action == "recrop":
                data = BoxSerializer(data=request.data)
                data.is_valid(raise_exception=True)
                verification_services.recrop_portrait(verification, data.validated_data["box"])
                log(request, "verification.recrop", "verification", pk, label)
            else:
                raise Http404
        except verification_services.VerificationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        verification = IV.objects.select_related("user__fundi_profile", "reviewed_by").get(pk=pk)
        return Response(VerificationSerializer(verification, context={"request": request}).data)


# --- fundis ----------------------------------------------------------------------------


class FundiListView(generics.ListAPIView):
    """?status=active|draft|paused|suspended|banned, ?q= business / name / phone / area."""

    permission_classes = [IsStaff]
    serializer_class = FundiSerializer

    def get_queryset(self):
        qs = FundiProfile.objects.select_related("user").prefetch_related("services__category").annotate(
            open_bookings=Count("bookings", filter=Q(bookings__status__in=Booking.OPEN_STATUSES))
        )
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(business_name__icontains=q) | Q(user__full_name__icontains=q) | Q(user__phone_number__icontains=q)
                | Q(user__email__icontains=q) | Q(area_text__icontains=q) | Q(region__icontains=q)
            )
        return qs.order_by("-created_at")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "discoverable_ids": set(FundiProfile.objects.discoverable().values_list("pk", flat=True))}


class FundiActionView(StaffView):
    """POST suspend {reason} | ban {reason} | reinstate {note}."""

    def post(self, request, pk, action):
        profile = get_object_or_404(FundiProfile.objects.select_related("user"), pk=pk)
        try:
            if action in ("suspend", "ban"):
                data = ReasonSerializer(data=request.data)
                data.is_valid(raise_exception=True)
                if profile.status == FundiProfile.Status.BANNED:
                    raise fundi_services.FundiError("This fundi is already banned.")
                fundi_services.suspend(profile, data.validated_data["reason"], actor=request.user, ban=action == "ban")
                log(request, f"fundi.{action}", "fundi", pk, profile.business_name, data.validated_data["reason"])
            elif action == "reinstate":
                data = NoteSerializer(data=request.data)
                data.is_valid(raise_exception=True)
                fundi_services.reinstate(profile)
                log(request, "fundi.reinstate", "fundi", pk, profile.business_name, data.validated_data["note"])
            else:
                raise Http404
        except fundi_services.FundiError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        profile = FundiListView(request=request).get_queryset().get(pk=pk)
        context = {"request": request, "discoverable_ids": set(FundiProfile.objects.discoverable().values_list("pk", flat=True))}
        return Response(FundiSerializer(profile, context=context).data)


# --- users -----------------------------------------------------------------------------


class UserListView(generics.ListAPIView):
    """?role=client|fundi|staff, ?active=0, ?q= name / email / phone."""

    permission_classes = [IsStaff]
    serializer_class = UserListSerializer

    def get_queryset(self):
        qs = User.objects.select_related("fundi_profile").annotate(bookings_count=Count("client_bookings", distinct=True))
        role = self.request.query_params.get("role")
        if role == "client":
            qs = qs.filter(fundi_profile__isnull=True, is_staff=False)
        elif role == "fundi":
            qs = qs.filter(fundi_profile__isnull=False)
        elif role == "staff":
            qs = qs.filter(is_staff=True)
        if self.request.query_params.get("active") == "0":
            qs = qs.filter(is_active=False)
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone_number__icontains=q))
        return qs.order_by("-date_joined")


class UserActionView(StaffView):
    """POST deactivate {reason} | activate | reverify {reason}."""

    def post(self, request, pk, action):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            raise ValidationError({"detail": "You can't change your own account here."})
        if user.is_superuser:
            raise ValidationError({"detail": "Superuser accounts are managed in Django admin."})
        label = user.full_name or user.email or user.phone_number
        if action == "deactivate":
            data = ReasonSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            user.is_active = False
            user.save(update_fields=["is_active"])
            profile = getattr(user, "fundi_profile", None)
            if profile and profile.status not in (FundiProfile.Status.SUSPENDED, FundiProfile.Status.BANNED):
                fundi_services.suspend(profile, data.validated_data["reason"], actor=request.user)
            # Their pending requests as a client are cancelled too.
            for booking in Booking.objects.filter(client=user, status__in=[B.REQUESTED, B.ACCEPTED]):
                booking_services.transition(booking, "cancel", actor=request.user, role=Booking.Party.ADMIN,
                                            note="Client account disabled")
            notify(user, "account.deactivated")
            log(request, "user.deactivate", "user", pk, label, data.validated_data["reason"])
        elif action == "activate":
            user.is_active = True
            user.save(update_fields=["is_active"])
            log(request, "user.activate", "user", pk, label)
        elif action == "reverify":
            data = ReasonSerializer(data=request.data)
            data.is_valid(raise_exception=True)
            try:
                verification_services.require_reverification(user, request.user, data.validated_data["reason"])
            except verification_services.VerificationError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            log(request, "user.reverify", "user", pk, label, data.validated_data["reason"])
        else:
            raise Http404
        user = UserListView(request=request).get_queryset().get(pk=pk)
        return Response(UserListSerializer(user, context={"request": request}).data)


# --- bookings --------------------------------------------------------------------------


class BookingListView(generics.ListAPIView):
    """?status=, ?q= reference / client / fundi."""

    permission_classes = [IsStaff]
    serializer_class = BookingSerializer

    def get_queryset(self):
        qs = Booking.objects.select_related("client", "fundi__user", "category", "review").prefetch_related("events__actor")
        status = self.request.query_params.get("status")
        if status:
            qs = qs.filter(status__in=status.split(","))
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(reference__icontains=q) | Q(client__full_name__icontains=q) | Q(client__phone_number__icontains=q)
                | Q(fundi__business_name__icontains=q) | Q(description__icontains=q)
            )
        return qs.order_by("-created_at")


class BookingDetailView(generics.RetrieveAPIView):
    permission_classes = [IsStaff]
    serializer_class = BookingSerializer
    queryset = Booking.objects.select_related("client", "fundi__user", "category", "review").prefetch_related(
        "events__actor"
    )


class BookingActionView(StaffView):
    """POST cancel {note} | resolve_close {note} | resolve_cancel {note}."""

    NOTE_REQUIRED = {"cancel", "resolve_close", "resolve_cancel"}

    def post(self, request, pk, action):
        if action not in self.NOTE_REQUIRED:
            raise Http404
        data = NoteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        note = data.validated_data["note"].strip()
        if not note:
            raise ValidationError({"note": "Explain the decision; both sides will see it."})
        booking = get_object_or_404(Booking, pk=pk)
        try:
            booking_services.transition(booking, action, actor=request.user, role=Booking.Party.ADMIN, note=note)
        except booking_services.BookingError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        log(request, f"booking.{action}", "booking", pk, booking.reference, note)
        return Response(BookingSerializer(BookingDetailView.queryset.get(pk=pk), context={"request": request}).data)


class ActionLogView(generics.ListAPIView):
    permission_classes = [IsStaff]
    serializer_class = StaffActionSerializer

    def get_queryset(self):
        qs = StaffAction.objects.select_related("actor")
        target = self.request.query_params.get("target")
        return qs.filter(target_id=target) if target else qs
