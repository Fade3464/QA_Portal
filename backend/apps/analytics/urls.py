from django.urls import path

from .views import GrafanaSalesDashboardView, GrafanaSalesXlsxExportView

urlpatterns = [
    path("grafana/sales/", GrafanaSalesDashboardView.as_view(), name="grafana-sales"),
    path("grafana/export/xlsx/", GrafanaSalesXlsxExportView.as_view(), name="grafana-sales-xlsx"),
]
