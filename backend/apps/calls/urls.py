from django.urls import path

from .views import (
    CallAnalysisView,
    CallFilterOptionsView,
    CallListView,
    CallReleaseView,
    CallReserveView,
    RecordingView,
)

urlpatterns = [
    path("", CallListView.as_view(), name="call-list"),
    path("filter-options/", CallFilterOptionsView.as_view(), name="call-filter-options"),
    path("<uuid:pk>/analysis/", CallAnalysisView.as_view(), name="call-analysis"),
    path("<uuid:pk>/reserve/", CallReserveView.as_view(), name="call-reserve"),
    path("<uuid:pk>/release/", CallReleaseView.as_view(), name="call-release"),
    path("<uuid:pk>/recording/", RecordingView.as_view(), name="call-recording"),
]
