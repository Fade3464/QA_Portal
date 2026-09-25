from django.urls import path

from .admin_views import CustomNotificationAdminView
from .views import (
    NotificationListView,
    NotificationReadAllView,
    NotificationReadView,
)

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("read-all/", NotificationReadAllView.as_view(), name="notification-read-all"),
    path(
        "admin/broadcasts/",
        CustomNotificationAdminView.as_view(),
        name="notification-admin-broadcasts",
    ),
    path("<uuid:pk>/read/", NotificationReadView.as_view(), name="notification-read"),
]
