from django.urls import path

from .consumers import AnalysisPresenceConsumer, NotificationConsumer

websocket_urlpatterns = [
    path("ws/notifications/", NotificationConsumer.as_asgi()),
    path(
        "ws/calls/<uuid:call_id>/analysis/",
        AnalysisPresenceConsumer.as_asgi(),
    ),
]
