import logging

import httpx
from celery import shared_task
from django.core.exceptions import ImproperlyConfigured

from apps.tenancy.models import Company
from .grafana import GrafanaAdminClient

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="analytics.sync_grafana_viewer",
    autoretry_for=(httpx.HTTPError, ImproperlyConfigured),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=6,
)
def sync_grafana_viewer(self, company_id: str):
    company = Company.objects.filter(pk=company_id).first()
    if not company:
        return {"status": "missing"}
    client = GrafanaAdminClient()
    if not company.analytics_enabled or not company.is_active:
        if company.grafana_user_id:
            try:
                client.delete_user(company.grafana_user_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
            Company.objects.filter(pk=company.pk).update(
                grafana_user_id=None, grafana_synced_username=""
            )
        return {"status": "disabled"}
    if not company.has_grafana_viewer_config:
        return {"status": "incomplete"}
    password = company.get_grafana_viewer_password()
    username = company.grafana_viewer_username.strip()
    if company.grafana_user_id and company.grafana_synced_username and company.grafana_synced_username != username:
        try:
            client.delete_user(company.grafana_user_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        company.grafana_user_id = None
        company.grafana_synced_username = ""
    current = client.lookup(username)
    if current is None:
        created = client.create_viewer(username, password) or {}
        user_id = created.get("id")
        if not user_id:
            current = client.lookup(username) or {}
            user_id = current.get("id")
    else:
        if current.get("isGrafanaAdmin"):
            raise ImproperlyConfigured(
                "Refusing to repurpose the Grafana server administrator as the shared viewer"
            )
        user_id = current.get("id")
    if not user_id:
        raise httpx.HTTPError("Grafana did not return the viewer user id")
    client.update_password(int(user_id), password)
    Company.objects.filter(pk=company.pk).update(
        grafana_user_id=int(user_id),
        grafana_synced_username=username,
    )
    return {"status": "synced", "company_id": str(company.pk)}


@shared_task(name="analytics.sync_all_grafana_viewers")
def sync_all_grafana_viewers():
    ids = Company.objects.filter(analytics_enabled=True, is_active=True).values_list("pk", flat=True)
    for company_id in ids:
        sync_grafana_viewer.delay(str(company_id))
    return {"queued": len(ids)}
