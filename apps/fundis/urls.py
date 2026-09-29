from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("fundi/services", views.MyServicesViewSet, basename="fundi-service")

urlpatterns = [
    path("fundi/profile/", views.MyFundiProfileView.as_view(), name="fundi-profile"),
    path("fundi/profile/activate/", views.ActivateProfileView.as_view(), name="fundi-activate"),
    path("fundi/profile/pause/", views.PauseProfileView.as_view(), name="fundi-pause"),
    path("fundis/search/", views.FundiSearchView.as_view(), name="fundi-search"),
    path("fundis/<uuid:pk>/", views.PublicFundiDetailView.as_view(), name="fundi-detail"),
    *router.urls,
]
