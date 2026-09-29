from rest_framework.routers import SimpleRouter

from .views import BookingViewSet

router = SimpleRouter()
router.register("bookings", BookingViewSet, basename="booking")

urlpatterns = router.urls
