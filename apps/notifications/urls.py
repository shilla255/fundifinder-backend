from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import DeviceView, NotificationViewSet

router = SimpleRouter()
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [path("notifications/devices/", DeviceView.as_view(), name="device"), *router.urls]
