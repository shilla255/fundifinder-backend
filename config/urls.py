from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "FundiFinder admin"
admin.site.site_title = "FundiFinder admin"

api_v1 = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.fundis.urls")),
    path("", include("apps.verification.urls")),
    path("", include("apps.bookings.urls")),
    path("", include("apps.notifications.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
]

if settings.DEBUG:
    # "Log in" link on the browsable API, handy with the seed_demo accounts.
    urlpatterns += [path("api-auth/", include("rest_framework.urls"))]
    # Public media only (fundi photos). ID documents live in private storage.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
