from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import IdentityVerification
from .serializers import VerificationStatusSerializer, VerificationSubmitSerializer

IMAGE_FIELDS = {"id_front_image", "id_back_image", "selfie_image"}


class MyVerificationView(APIView):
    """GET: current identity status and latest submission. POST: submit NIDA details + photos."""

    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        latest = request.user.identity_verifications.first()
        current = services.current_document(request.user)
        ctx = {"request": request}
        return Response(
            {
                "identity_status": request.user.identity_status,
                "latest_submission": VerificationStatusSerializer(latest, context=ctx).data if latest else None,
                # The approved document the public photo comes from.
                "current_document": VerificationStatusSerializer(current, context=ctx).data if current else None,
                # Documents this person may submit now (verified people can only upgrade).
                "can_submit": services.submittable_documents(request.user),
            }
        )

    def post(self, request):
        serializer = VerificationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            verification = services.submit(request.user, **serializer.validated_data)
        except services.VerificationError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(
            VerificationStatusSerializer(verification, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@staff_member_required
def private_image(request, pk, field):
    """Stream an ID document to staff only. Files are never reachable by public URL."""
    if field not in IMAGE_FIELDS or not request.user.has_perm("verification.view_identityverification"):
        raise Http404
    verification = get_object_or_404(IdentityVerification, pk=pk)
    image = getattr(verification, field)
    if not image:
        raise Http404
    response = FileResponse(image.open("rb"))
    response["Cache-Control"] = "private, no-store"
    return response
