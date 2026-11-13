from django.urls import path

from .views import DashboardSummaryView, DialerManagerObservabilityView, ProjectPerformanceView

urlpatterns = [
    path("observability/", DialerManagerObservabilityView.as_view(), name="dialer-manager-observability"),
    path("summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path(
        "project-performance/",
        ProjectPerformanceView.as_view(),
        name="project-performance",
    ),
]
