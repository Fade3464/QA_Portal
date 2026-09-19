from django.urls import path

from .views import DashboardSummaryView, ProjectPerformanceView

urlpatterns = [
    path("summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path(
        "project-performance/",
        ProjectPerformanceView.as_view(),
        name="project-performance",
    ),
]
