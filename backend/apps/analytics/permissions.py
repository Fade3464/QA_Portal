import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class HasGrafanaAnalyticsToken(BasePermission):
    message = "Invalid analytics service token."

    def has_permission(self, request, view):
        expected = settings.GRAFANA_ANALYTICS_API_TOKEN
        if not expected:
            return False
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        supplied = header[7:].strip()
        return bool(supplied and hmac.compare_digest(supplied, expected))


class HasGrafanaExportProxy(BasePermission):
    """Allow XLSX export only through the authenticated frontend Grafana proxy."""

    message = "Grafana export proxy authentication is required."

    def has_permission(self, request, view):
        return request.headers.get("X-Grafana-Export-Authorized", "") == "1"
