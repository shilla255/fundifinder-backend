from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("fundi/services", views.MyServicesViewSet, basename="fundi-service")
router.register("fundi/work-photos", views.MyWorkPhotosViewSet, basename="fundi-work-photo")

urlpatterns = [
    path("fundi/profile/", views.MyFundiProfileView.as_view(), name="fundi-profile"),
    path("fundi/profile/activate/", views.ActivateProfileView.as_view(), name="fundi-activate"),
    path("fundi/profile/pause/", views.PauseProfileView.as_view(), name="fundi-pause"),
    path("fundi/stats/", views.MyFundiStatsView.as_view(), name="fundi-stats"),
    path("fundis/search/", views.FundiSearchView.as_view(), name="fundi-search"),
    path("fundis/top/", views.TopFundisView.as_view(), name="fundi-top"),
    path("me/favorites/", views.MyFavoritesView.as_view(), name="favorites"),
    path("me/favorites/<uuid:pk>/", views.MyFavoriteDetailView.as_view(), name="favorite-detail"),
    path("fundis/<uuid:pk>/", views.PublicFundiDetailView.as_view(), name="fundi-detail"),
    path("fundis/<uuid:pk>/reviews/", views.PublicFundiReviewsView.as_view(), name="fundi-reviews"),
    *router.urls,
]
