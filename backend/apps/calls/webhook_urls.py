from django.urls import path

from .webhooks import receive_vicidial

urlpatterns = [
    path(
        "<uuid:dialer_id>/<str:event_type>/", receive_vicidial, name="vicidial-webhook"
    ),
]
