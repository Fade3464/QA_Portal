from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import HasGrafanaAnalyticsToken
from .services.sales import build_sales_dashboard


class GrafanaSalesDashboardView(APIView):
    authentication_classes = []
    permission_classes = [HasGrafanaAnalyticsToken]

    def get(self, request):
        return Response(
            build_sales_dashboard(
                from_ms=request.query_params.get("from"),
                to_ms=request.query_params.get("to"),
                team=request.query_params.get("team", ""),
                project=request.query_params.getlist("project"),
                preset=request.query_params.get("preset", ""),
            )
        )
