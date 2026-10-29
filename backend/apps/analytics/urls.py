from django.urls import path

from .views import GrafanaSalesDashboardView

urlpatterns = [
    path("grafana/sales/", GrafanaSalesDashboardView.as_view(), name="grafana-sales"),
]
