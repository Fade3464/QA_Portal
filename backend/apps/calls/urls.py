from django.urls import path

from .views import CallListView, RecordingView

urlpatterns = [
    path("", CallListView.as_view(), name="call-list"),
    path("<uuid:pk>/recording/", RecordingView.as_view(), name="call-recording"),
]
