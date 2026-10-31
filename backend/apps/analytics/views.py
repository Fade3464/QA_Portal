from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import HasGrafanaAnalyticsToken, HasGrafanaExportProxy
from .services.sales import build_sales_dashboard
from .services.xlsx import build_sales_xlsx


class GrafanaSalesDashboardView(APIView):
    authentication_classes = []
    permission_classes = [HasGrafanaAnalyticsToken]

    def get(self, request):
        payload = build_sales_dashboard(
            from_ms=request.query_params.get("from"),
            to_ms=request.query_params.get("to"),
            team=request.query_params.get("team", ""),
            project=request.query_params.getlist("project"),
            preset=request.query_params.get("preset", ""),
        )
        # Agent/team table views intentionally return a root-level array so the
        # Infinity datasource can auto-discover the data-driven preset columns.
        # All other callers keep the original aggregate response contract.
        section = request.query_params.get("section", "").strip()
        if section in {"agent_table", "team_table"}:
            return Response(payload.get(section, []))
        return Response(payload)


class GrafanaSalesXlsxExportView(APIView):
    authentication_classes = []
    permission_classes = [HasGrafanaExportProxy]

    @staticmethod
    def _single_param(request, name):
        # Dashboard links use Grafana's includeVars option, which appends
        # variables as var-<name>. Keep accepting the older explicit panel-link
        # parameters too so existing bookmarked export URLs continue working.
        return request.query_params.get(name, request.query_params.get(f"var-{name}", ""))

    @staticmethod
    def _multi_param(request, name):
        values = request.query_params.getlist(name)
        if values:
            return values
        return request.query_params.getlist(f"var-{name}")

    def get(self, request):
        payload = build_sales_dashboard(
            from_ms=request.query_params.get("from"),
            to_ms=request.query_params.get("to"),
            team=self._single_param(request, "team"),
            project=self._multi_param(request, "project"),
            preset=self._single_param(request, "preset"),
        )
        try:
            content, filename = build_sales_xlsx(
                payload, request.query_params.get("table", "")
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response
