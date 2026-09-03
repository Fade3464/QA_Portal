from django.urls import path

from .views import CallFilterOptionsView, CallListView, RecordingView

urlpatterns = [
    path("", CallListView.as_view(), name="call-list"),
    path("filter-options/", CallFilterOptionsView.as_view(), name="call-filter-options"),
    path("<uuid:pk>/recording/", RecordingView.as_view(), name="call-recording"),
]
