from rest_framework import generics, status
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import OTPChallenge
from .serializers import (
    FirebaseSignInSerializer,
    GoogleSignInSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    UserSerializer,
)


def _auth_response(user, created):
    return Response(
        {**services.issue_tokens(user), "user": UserSerializer(user).data, "created": created},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


class GoogleSignInView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = GoogleSignInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user, created = services.sign_in_with_google(serializer.validated_data["id_token"])
        except services.AuthError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return _auth_response(user, created)


class FirebaseSignInView(APIView):
    """Phone sign-in via Firebase Authentication (web and mobile apps).

    purpose=login (default): sign in or sign up with the phone number.
    purpose=verify_phone: attach the verified number to the signed-in account.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = FirebaseSignInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["id_token"]
        try:
            if serializer.validated_data["purpose"] == OTPChallenge.Purpose.VERIFY_PHONE:
                if not request.user.is_authenticated:
                    raise NotAuthenticated()
                user = services.verify_phone_with_firebase(request.user, token)
                return Response(UserSerializer(user).data)
            user, created = services.sign_in_with_firebase(token)
        except services.AuthError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return _auth_response(user, created)


class OTPRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp"

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        purpose = serializer.validated_data["purpose"]
        user = None
        if purpose == OTPChallenge.Purpose.VERIFY_PHONE:
            if not request.user.is_authenticated:
                raise NotAuthenticated()
            user = request.user
        try:
            services.request_otp(
                serializer.validated_data["phone_number"],
                purpose,
                user=user,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except services.AuthError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response({"detail": "Code sent."}, status=status.HTTP_202_ACCEPTED)


class OTPVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            if data["purpose"] == OTPChallenge.Purpose.VERIFY_PHONE:
                if not request.user.is_authenticated:
                    raise NotAuthenticated()
                user = services.verify_phone_for_user(
                    request.user, data["phone_number"], data["code"]
                )
                return Response(UserSerializer(user).data)
            user, created = services.sign_in_with_otp(data["phone_number"], data["code"])
        except services.AuthError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return _auth_response(user, created)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user
