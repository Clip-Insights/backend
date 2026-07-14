from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from core.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check),
    path("api/videos/", include("videos.urls")),
    path("api/files/", include("files.urls")),
    path("api/account/", include("account.urls")),
    path("api/plans/", include("plans.urls")),
    path("api/billing/", include("billing.urls")),
    # backward-compat aliases
    path("api/textutils/", include("videos.urls")),
    path("api/userspace/", include("files.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
