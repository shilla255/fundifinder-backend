from rest_framework.routers import SimpleRouter

from django.urls import path

from .views import BookingViewSet, FeaturedReviewsView

router = SimpleRouter()
router.register("bookings", BookingViewSet, basename="booking")

urlpatterns = [
    path("reviews/featured/", FeaturedReviewsView.as_view(), name="featured-reviews"),
    *router.urls,
]
