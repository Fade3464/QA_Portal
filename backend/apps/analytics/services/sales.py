from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, ROUND_HALF_UP

from django.core.cache import cache
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, TruncDate, TruncHour
from django.utils import timezone

from apps.calls.models import CallEvent
from apps.tenancy.models import Company, DialerCampaign


def _pct(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return float((Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def active_analytics_company() -> Company | None:
    return Company.objects.filter(analytics_enabled=True, is_active=True).first()


def _parse_epoch_ms(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        raw = int(value)
        return datetime.fromtimestamp(raw / 1000, tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return fallback


def _clean_filter(value: str | None) -> str:
    value = (value or "").strip()
    if value.casefold() in {"", "all", "__all", "$__all"}:
        return ""
    return value


def _clean_multi_filter(value) -> tuple[str, ...]:
    """Normalize Grafana multi-value filters without changing legacy callers.

    The dashboard sends one ``project=...`` query parameter per selected
    project. Pipe-delimited values are also accepted for backwards-compatible
    callers. Selecting Grafana's custom All value deliberately removes the
    project restriction.
    """
    if value is None:
        return ()
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    values: list[str] = []
    for raw in raw_values:
        values.extend(part.strip() for part in str(raw or "").split("|"))
    values = [item for item in values if item]
    if not values or any(item.casefold() in {"all", "__all", "$__all"} for item in values):
        return ()
    # Preserve dashboard order while removing accidental duplicates.
    return tuple(dict.fromkeys(values))


def _base_queryset(company: Company, start: datetime, end: datetime, *, team="", project="", preset=""):
    project_subquery = DialerCampaign.objects.filter(
        dialer_id=OuterRef("dialer_id"),
        campaign__iexact=OuterRef("campaign"),
    ).values("project_name")[:1]
    qs = (
        CallEvent.objects.filter(branch__company=company)
        .filter(
            Q(call_date__gte=start, call_date__lte=end)
            | Q(
                call_date__isnull=True,
                finalized_at__gte=start,
                finalized_at__lte=end,
            )
            | Q(
                call_date__isnull=True,
                finalized_at__isnull=True,
                received_at__gte=start,
                received_at__lte=end,
            )
        )
        .annotate(analytics_at=Coalesce("call_date", "finalized_at", "received_at"))
        .annotate(project_name=Subquery(project_subquery))
    )
    team = _clean_filter(team)
    projects = _clean_multi_filter(project)
    preset = _clean_filter(preset)
    if team:
        qs = qs.filter(Q(team__name=team) | Q(team_name=team))
    if projects:
        project_filter = Q()
        for project_name in projects:
            project_filter |= Q(project_name__iexact=project_name)
        qs = qs.filter(project_filter)
    if preset:
        qs = qs.filter(preset=preset)
    return qs


def _sale_metrics(qs):
    return qs.filter(disposition__iexact="SALE").aggregate(
        opportunities=Count("id"),
        sold_count=Count("id", filter=Q(sold=True)),
        transfers=Count("id", filter=Q(sold=False)),
        twenty_plus=Count("id", filter=Q(client_20_plus=True)),
        thirty_plus=Count("id", filter=Q(client_30_plus=True)),
        missing_preset=Count("id", filter=Q(preset__isnull=True) | Q(preset="")),
        twenty_plus_sold=Count("id", filter=Q(client_20_plus=True, sold=True)),
        thirty_plus_sold=Count("id", filter=Q(client_30_plus=True, sold=True)),
        under_20=Count("id", filter=Q(client_20_plus=False)),
    )


def _decorate(rows):
    result=[]
    for row in rows:
        item=dict(row)
        opportunities=int(item.get("opportunities") or 0)
        sold=int(item.pop("sold_count", 0) or 0)
        item["sold"] = sold
        item["conversion_pct"]=_pct(sold, opportunities)
        item["twenty_plus_pct"]=_pct(int(item.get("twenty_plus") or 0), opportunities)
        item["thirty_plus_pct"]=_pct(int(item.get("thirty_plus") or 0), opportunities)
        result.append(item)
    return result


def _grouped(qs, fields, order_by="-sold_count"):
    rows=(
        qs.filter(disposition__iexact="SALE")
        .values(*fields)
        .annotate(
            opportunities=Count("id"),
            sold_count=Count("id", filter=Q(sold=True)),
            transfers=Count("id", filter=Q(sold=False)),
            twenty_plus=Count("id", filter=Q(client_20_plus=True)),
            thirty_plus=Count("id", filter=Q(client_30_plus=True)),
            missing_preset=Count("id", filter=Q(preset__isnull=True) | Q(preset="")),
        )
        .order_by(order_by, "-opportunities")[:250]
    )
    return _decorate(rows)


def _sold_detail_rows(qs):
    rows = []
    for event in (
        qs.filter(disposition__iexact="SALE", sold=True)
        .select_related("team")
        .order_by("-analytics_at", "-received_at")[:500]
    ):
        team_name = (event.team.name if event.team_id else event.team_name) or "Unassigned"
        rows.append(
            {
                "agent": event.agent_name or event.agent_user or "Unknown",
                "team": team_name,
                "number": event.phone_number or "",
                "client": event.preset or "Unresolved",
                "client_status": event.client_status or "",
                "disposition_time": event.analytics_at.isoformat() if getattr(event, "analytics_at", None) else "",
            }
        )
    return rows


def build_sales_dashboard(*, from_ms=None, to_ms=None, team="", project="", preset=""):
    company=active_analytics_company()
    if not company:
        return {"enabled": False, "message": "Sales analytics is not enabled for a company."}
    now=timezone.now()
    end=_parse_epoch_ms(to_ms, now)
    start=_parse_epoch_ms(from_ms, end-timedelta(hours=24))
    if start>end:
        start,end=end,start
    if end-start>timedelta(days=366):
        start=end-timedelta(days=366)
    # Round the cache window to a minute so Grafana auto-refreshes reuse the same
    # aggregate response while still remaining operationally current.
    start_key=int(start.timestamp()//60)
    end_key=int(end.timestamp()//60)
    filters=(_clean_filter(team),_clean_multi_filter(project),_clean_filter(preset))
    # Keep Redis/memcached keys bounded even when many projects are selected.
    filter_signature = hashlib.sha256(
        json.dumps(filters, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:20]
    cache_key=f"sales-analytics:v7:{company.pk}:{start_key}:{end_key}:{filter_signature}"
    cached=cache.get(cache_key)
    if cached is not None:
        return cached
    qs=_base_queryset(company,start,end,team=team,project=project,preset=preset)
    sale_qs=qs.filter(disposition__iexact="SALE")
    metrics=_sale_metrics(qs)
    opportunities=int(metrics["opportunities"] or 0)
    sold=int(metrics.pop("sold_count", 0) or 0)
    metrics["sold"] = sold
    metrics.update({
        "conversion_pct": _pct(sold, opportunities),
        "twenty_plus_pct": _pct(int(metrics["twenty_plus"] or 0), opportunities),
        "thirty_plus_pct": _pct(int(metrics["thirty_plus"] or 0), opportunities),
        "under_20_pct": _pct(int(metrics["under_20"] or 0), opportunities),
        "twenty_plus_conversion_pct": _pct(
            int(metrics["twenty_plus_sold"] or 0), int(metrics["twenty_plus"] or 0)
        ),
        "thirty_plus_conversion_pct": _pct(
            int(metrics["thirty_plus_sold"] or 0), int(metrics["thirty_plus"] or 0)
        ),
        "stale_calls": qs.filter(stale=True).count(),
    })
    summary=[metrics]
    teams=_grouped(sale_qs, ["team__name", "team__team_leader__first_name", "team__team_leader__last_name"])
    for row in teams:
        row["team"] = row.pop("team__name") or "Unassigned"
        first=row.pop("team__team_leader__first_name") or ""
        last=row.pop("team__team_leader__last_name") or ""
        row["team_leader"]=(f"{first} {last}".strip() or "Unassigned")
    presets=_grouped(sale_qs,["preset"])
    for row in presets:
        row["preset"] = row.get("preset") or "Unresolved"
    projects=_grouped(sale_qs,["project_name"])
    for row in projects:
        row["project"] = row.pop("project_name") or "Unmapped"
    agents=_grouped(
        sale_qs,
        [
            "agent_user",
            "agent_name",
            "team__team_leader__first_name",
            "team__team_leader__last_name",
        ],
    )
    for row in agents:
        row["agent"] = row.get("agent_name") or row.get("agent_user") or "Unknown"
        first = row.pop("team__team_leader__first_name") or ""
        last = row.pop("team__team_leader__last_name") or ""
        row["team_leader"] = f"{first} {last}".strip() or "Unassigned"
    trend_bucket = TruncHour if end - start <= timedelta(days=2) else TruncDate
    trends=(
        sale_qs.annotate(bucket=trend_bucket("analytics_at"))
        .values("bucket")
        .annotate(
            opportunities=Count("id"),
            sold_count=Count("id", filter=Q(sold=True)),
            transfers=Count("id", filter=Q(sold=False)),
            twenty_plus=Count("id", filter=Q(client_20_plus=True)),
            thirty_plus=Count("id", filter=Q(client_30_plus=True)),
        )
        .order_by("bucket")
    )
    trend_rows=[]
    for row in trends:
        item=dict(row)
        item["date"]=item.pop("bucket").isoformat() if item.get("bucket") else ""
        sold=int(item.pop("sold_count", 0) or 0)
        item["sold"] = sold
        item["conversion_pct"]=_pct(sold,int(item.get("opportunities") or 0))
        trend_rows.append(item)
    filter_cache=f"sales-analytics:filters:v2:{company.pk}:{start_key}:{end_key}"
    filter_values=cache.get(filter_cache)
    if filter_values is None:
        base=_base_queryset(company,start,end)
        filter_values={
            "teams": [{"text": value, "value": value} for value in sorted(set(base.exclude(team__name__isnull=True).exclude(team__name="").values_list("team__name",flat=True)))],
            "projects": [{"text": value, "value": value} for value in sorted(set(base.exclude(project_name__isnull=True).exclude(project_name="").values_list("project_name",flat=True)))],
            "presets": [{"text": value, "value": value} for value in sorted(set(base.filter(disposition__iexact="SALE").exclude(preset__isnull=True).exclude(preset="").values_list("preset",flat=True)))],
        }
        cache.set(filter_cache,filter_values,300)
    sold_details = _sold_detail_rows(qs)
    payload={
        "enabled": True,
        "company": company.name,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "summary": summary,
        "teams": teams,
        "presets": presets,
        "projects": projects,
        "agents": agents,
        "top_agents": agents[:10],
        "trend": trend_rows,
        "trend_granularity": "hour" if trend_bucket is TruncHour else "day",
        "sold_details": sold_details,
        "filters": filter_values,
    }
    cache.set(cache_key,payload,60)
    return payload
