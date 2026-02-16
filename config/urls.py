from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.account.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health),
    path("api/auth/", include("apps.account.urls")),
    path("api/fortune/", include("apps.fortune.urls")),
    path("api/community/", include("apps.community.urls")),
    path("api/config/", include("apps.system.urls")),
    path("api/im/", include("apps.im.urls")),
    path("api/admin/", include("apps.admin_api.urls")),
]
if settings.DEBUG and settings.MEDIA_ROOT:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
