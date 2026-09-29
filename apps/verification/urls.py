from django.urls import path

from . import views

urlpatterns = [
    path("verification/", views.MyVerificationView.as_view(), name="verification"),
]
