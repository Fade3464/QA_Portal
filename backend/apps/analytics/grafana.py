from __future__ import annotations

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class GrafanaAdminClient:
    def __init__(self):
        if not settings.GRAFANA_SERVICE_ADMIN_PASSWORD:
            raise ImproperlyConfigured("GRAFANA_SERVICE_ADMIN_PASSWORD is required")
        self.base_url = settings.GRAFANA_SERVICE_URL.rstrip("/")
        self.auth = httpx.BasicAuth(
            settings.GRAFANA_SERVICE_ADMIN_USER,
            settings.GRAFANA_SERVICE_ADMIN_PASSWORD,
        )

    def _request(self, method: str, path: str, **kwargs):
        with httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
            response = client.request(method, f"{self.base_url}{path}", auth=self.auth, **kwargs)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else {}

    def lookup(self, login: str):
        return self._request("GET", "/api/users/lookup", params={"loginOrEmail": login})

    def create_viewer(self, login: str, password: str):
        payload = {
            "name": "CallLens Sales Analytics",
            "email": f"{login}@calllens.local",
            "login": login,
            "password": password,
        }
        return self._request("POST", "/api/admin/users", json=payload)

    def update_password(self, user_id: int, password: str):
        return self._request(
            "PUT", f"/api/admin/users/{user_id}/password", json={"password": password}
        )

    def delete_user(self, user_id: int):
        return self._request("DELETE", f"/api/admin/users/{user_id}")
