from django.urls import path
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

from . import views

urlpatterns = [
    path("auth/google/", views.GoogleSignInView.as_view(), name="auth-google"),
    path("auth/otp/request/", views.OTPRequestView.as_view(), name="auth-otp-request"),
    path("auth/otp/verify/", views.OTPVerifyView.as_view(), name="auth-otp-verify"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("auth/logout/", TokenBlacklistView.as_view(), name="auth-logout"),
    path("me/", views.MeView.as_view(), name="me"),
]
