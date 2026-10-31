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


def _agent_rows_with_activity(activity_qs, sale_qs):
    """Return active agents even when they have no SALE rows in the range.

    Agent membership comes from all call records in the selected time/team/project
    scope. SALE metrics are overlaid from the fully-filtered SALE queryset, so a
    client/preset filter still affects the metrics without removing otherwise
    active agents from the leaderboard.
    """
    fields = [
        "agent_user",
        "agent_name",
        "team__team_leader__first_name",
        "team__team_leader__last_name",
    ]

    sale_rows = _grouped(sale_qs, fields)

    def identity(row):
        return tuple(row.get(field) or "" for field in fields)

    sale_by_identity = {identity(row): row for row in sale_rows}
    active_rows = (
        activity_qs.exclude(agent_user="", agent_name="")
        .values(*fields)
        .annotate(activity_count=Count("id"))
        .order_by()[:250]
    )

    result = []
    for active in active_rows:
        key = identity(active)
        sale = sale_by_identity.get(key)
        if sale is None:
            row = {field: active.get(field) for field in fields}
            row.update(
                {
                    "opportunities": 0,
                    "sold": 0,
                    "transfers": 0,
                    "twenty_plus": 0,
                    "thirty_plus": 0,
                    "missing_preset": 0,
                    "conversion_pct": 0.0,
                    "twenty_plus_pct": 0.0,
                    "thirty_plus_pct": 0.0,
                }
            )
        else:
            row = dict(sale)

        row["agent"] = row.get("agent_name") or row.get("agent_user") or "Unknown"
        first = row.pop("team__team_leader__first_name", None) or ""
        last = row.pop("team__team_leader__last_name", None) or ""
        row["team_leader"] = f"{first} {last}".strip() or "Unassigned"
        result.append(row)

    # Keep the API stable for Top sellers. Grafana applies its own Team leader
    # grouping/sort to the full Agent leaderboard table.
    result.sort(
        key=lambda row: (
            -int(row.get("sold") or 0),
            -int(row.get("transfers") or 0),
            str(row.get("agent") or "").casefold(),
        )
    )
    return result[:250]


def _available_presets(sale_qs) -> list[str]:
    """Return the currently-visible resolved presets in stable display order."""
    values = sale_qs.exclude(preset__isnull=True).exclude(preset="").values_list(
        "preset", flat=True
    )
    return sorted(set(values), key=lambda value: value.casefold())


def _agent_preset_transfer_counts(
    sale_qs,
) -> dict[tuple[str, str, str], dict[str, int]]:
    rows = (
        sale_qs.filter(sold=False)
        .exclude(preset__isnull=True)
        .exclude(preset="")
        .values(
            "agent_user",
            "agent_name",
            "team__team_leader__first_name",
            "team__team_leader__last_name",
            "preset",
        )
        .annotate(count=Count("id"))
    )
    result: dict[tuple[str, str, str], dict[str, int]] = {}
    for row in rows:
        first = row.get("team__team_leader__first_name") or ""
        last = row.get("team__team_leader__last_name") or ""
        leader = f"{first} {last}".strip() or "Unassigned"
        key = (
            row.get("agent_user") or "",
            row.get("agent_name") or "",
            leader,
        )
        per_preset = result.setdefault(key, {})
        per_preset[row["preset"]] = per_preset.get(row["preset"], 0) + int(
            row["count"] or 0
        )
    return result


def _team_preset_transfer_counts(sale_qs) -> dict[str, dict[str, int]]:
    rows = (
        sale_qs.filter(sold=False)
        .exclude(preset__isnull=True)
        .exclude(preset="")
        .values("team__name", "team_name", "preset")
        .annotate(count=Count("id"))
    )
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        team_name = row.get("team__name") or row.get("team_name") or "Unassigned"
        per_preset = result.setdefault(team_name, {})
        per_preset[row["preset"]] = per_preset.get(row["preset"], 0) + int(
            row["count"] or 0
        )
    return result


def _agent_table_rows(agents, sale_qs, *, include_preset_columns: bool):
    presets = _available_presets(sale_qs) if include_preset_columns else []
    transfer_counts = (
        _agent_preset_transfer_counts(sale_qs) if include_preset_columns else {}
    )
    rows = []
    for row in agents:
        # Keep the fixed performance columns first. Dynamic preset columns are
        # deliberately appended after Conversion % so the API contract matches
        # the intended Grafana table layout.
        item = {
            "Agent": row["agent"],
            "Team leader": row["team_leader"],
            "Sold": int(row.get("sold") or 0),
            "30+": int(row.get("thirty_plus") or 0),
            "Transfers": int(row.get("transfers") or 0),
            "Conversion %": float(row.get("conversion_pct") or 0),
        }
        per_preset = transfer_counts.get(
            (
                row.get("agent_user") or "",
                row.get("agent_name") or "",
                row["team_leader"],
            ),
            {},
        )
        for preset_name in presets:
            item[preset_name] = per_preset.get(preset_name, 0)
        rows.append(item)
    return rows


def _team_table_rows(teams, sale_qs, *, include_preset_columns: bool):
    presets = _available_presets(sale_qs) if include_preset_columns else []
    transfer_counts = (
        _team_preset_transfer_counts(sale_qs) if include_preset_columns else {}
    )
    rows = []
    for row in teams:
        # As with the agent table, keep every data-driven preset field to the
        # right of the fixed performance columns.
        item = {
            "Team": row["team"],
            "Team leader": row["team_leader"],
            "Sold": int(row.get("sold") or 0),
            "30+": int(row.get("thirty_plus") or 0),
            "Transfers": int(row.get("transfers") or 0),
            "Conversion %": float(row.get("conversion_pct") or 0),
        }
        per_preset = transfer_counts.get(row["team"], {})
        for preset_name in presets:
            item[preset_name] = per_preset.get(preset_name, 0)
        rows.append(item)
    return rows


def _call_detail_rows(qs, *, sold: bool):
    """Return dashboard-safe SALE call details for sold or transfer rows."""
    rows = []
    for event in (
        qs.filter(disposition__iexact="SALE", sold=sold)
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


def _sold_detail_rows(qs):
    return _call_detail_rows(qs, sold=True)


def _transfer_detail_rows(qs):
    return _call_detail_rows(qs, sold=False)


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
    cache_key=f"sales-analytics:v12:{company.pk}:{start_key}:{end_key}:{filter_signature}"
    cached=cache.get(cache_key)
    if cached is not None:
        return cached
    qs=_base_queryset(company,start,end,team=team,project=project,preset=preset)
    # Leaderboard membership deliberately ignores the client/preset filter so
    # active agents remain visible with zero SALE metrics when appropriate.
    activity_qs=(
        _base_queryset(company,start,end,team=team,project=project,preset="")
        .exclude(disposition__in=CallEvent.PROVISIONAL_START_DISPOSITIONS)
    )
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
    agents=_agent_rows_with_activity(activity_qs, sale_qs)
    include_preset_columns = not bool(_clean_filter(preset))
    agent_table = _agent_table_rows(
        agents, sale_qs, include_preset_columns=include_preset_columns
    )
    team_table = _team_table_rows(
        teams, sale_qs, include_preset_columns=include_preset_columns
    )
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
    transfer_details = _transfer_detail_rows(qs)
    payload={
        "enabled": True,
        "company": company.name,
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "summary": summary,
        "teams": teams,
        "presets": presets,
        "projects": projects,
        "agents": agents,
        "agent_table": agent_table,
        "team_table": team_table,
        "top_agents": agents[:10],
        "trend": trend_rows,
        "trend_granularity": "hour" if trend_bucket is TruncHour else "day",
        "sold_details": sold_details,
        "transfer_details": transfer_details,
        "filters": filter_values,
    }
    cache.set(cache_key,payload,60)
    return payload
