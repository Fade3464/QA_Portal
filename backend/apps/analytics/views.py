from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import HasGrafanaAnalyticsToken
from .services.sales import build_sales_dashboard


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
