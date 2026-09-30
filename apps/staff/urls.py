from django.urls import path

from . import views

urlpatterns = [
    path("overview/", views.OverviewView.as_view(), name="staff-overview"),
    path("verifications/", views.VerificationListView.as_view(), name="staff-verifications"),
    path("verifications/<uuid:pk>/", views.VerificationDetailView.as_view(), name="staff-verification"),
    path("verifications/<uuid:pk>/image/<str:field>/", views.VerificationImageView.as_view(), name="staff-verification-image"),
    path("verifications/<uuid:pk>/<str:action>/", views.VerificationActionView.as_view(), name="staff-verification-action"),
    path("fundis/", views.FundiListView.as_view(), name="staff-fundis"),
    path("fundis/<uuid:pk>/<str:action>/", views.FundiActionView.as_view(), name="staff-fundi-action"),
    path("users/", views.UserListView.as_view(), name="staff-users"),
    path("users/<uuid:pk>/<str:action>/", views.UserActionView.as_view(), name="staff-user-action"),
    path("bookings/", views.BookingListView.as_view(), name="staff-bookings"),
    path("bookings/<uuid:pk>/", views.BookingDetailView.as_view(), name="staff-booking"),
    path("bookings/<uuid:pk>/<str:action>/", views.BookingActionView.as_view(), name="staff-booking-action"),
    path("actions/", views.ActionLogView.as_view(), name="staff-actions"),
]
