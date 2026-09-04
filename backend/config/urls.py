from django.contrib import admin
from django.urls import include, path

from apps.dashboard.views import health

admin.site.site_header = "QA Portal Administration"
admin.site.site_title = "QA Portal Admin"
admin.site.index_title = "System configuration"
admin.site.has_permission = lambda request: (
    request.user.is_active and request.user.is_superuser
)

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/dashboard/", include("apps.dashboard.urls")),
    path("api/v1/administration/", include("apps.tenancy.api_urls")),
    path("api/v1/calls/", include("apps.calls.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/webhooks/vicidial/", include("apps.calls.webhook_urls")),
]
