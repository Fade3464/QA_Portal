from django.urls import path

from .views import (
    CallAnalysisView,
    CallFilterOptionsView,
    CallListView,
    CallReleaseView,
    CallReviewDraftView,
    CallReviewSubmitView,
    CallReserveView,
    RecordingView,
    ReviewReportListView,
)

urlpatterns = [
    path("", CallListView.as_view(), name="call-list"),
    path("filter-options/", CallFilterOptionsView.as_view(), name="call-filter-options"),
    path("reports/", ReviewReportListView.as_view(), name="review-report-list"),
    path("<uuid:pk>/analysis/", CallAnalysisView.as_view(), name="call-analysis"),
    path("<uuid:pk>/reserve/", CallReserveView.as_view(), name="call-reserve"),
    path("<uuid:pk>/release/", CallReleaseView.as_view(), name="call-release"),
    path("<uuid:pk>/review/", CallReviewDraftView.as_view(), name="call-review-draft"),
    path(
        "<uuid:pk>/review/submit/",
        CallReviewSubmitView.as_view(),
        name="call-review-submit",
    ),
    path("<uuid:pk>/recording/", RecordingView.as_view(), name="call-recording"),
]
