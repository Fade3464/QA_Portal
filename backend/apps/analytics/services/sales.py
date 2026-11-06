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


AREA_CODES_BY_STATE = {
    "AL": "205, 251, 256, 334, 659, 938",
    "AK": "907",
    "AZ": "480, 520, 602, 623, 928",
    "AR": "479, 501, 870",
    "CA": "209, 213, 279, 310, 323, 341, 369, 408, 415, 424, 442, 510, 530, 559, 562, 619, 626, 627, 628, 650, 657, 661, 669, 707, 714, 747, 760, 764, 805, 818, 820, 831, 858, 909, 916, 925, 935, 949, 951",
    "CO": "303, 719, 720, 970",
    "CT": "203, 475, 860, 959",
    "DE": "302",
    "DC": "202",
    "FL": "239, 305, 321, 352, 386, 407, 561, 689, 727, 754, 772, 786, 813, 850, 863, 904, 941, 954",
    "GA": "229, 404, 470, 478, 678, 706, 762, 770, 912",
    "HI": "808",
    "ID": "208, 986",
    "IL": "217, 224, 309, 312, 331, 464, 618, 630, 708, 773, 779, 815, 847, 872",
    "IN": "219, 260, 317, 463, 574, 765, 812, 930",
    "IA": "319, 515, 563, 641, 712",
    "KS": "316, 620, 785, 913",
    "KY": "270, 364, 502, 606, 859",
    "LA": "225, 318, 337, 504, 985",
    "ME": "207",
    "MD": "227, 240, 301, 410, 443, 667",
    "MA": "339, 351, 413, 508, 617, 774, 781, 857, 978",
    "MI": "231, 248, 269, 278, 313, 517, 586, 616, 679, 734, 810, 906, 947, 989",
    "MN": "218, 320, 507, 612, 651, 763, 952",
    "MS": "228, 601, 662, 769",
    "MO": "314, 417, 557, 573, 636, 660, 816, 975",
    "MT": "406",
    "NE": "308, 402, 531",
    "NV": "702, 725, 775",
    "NH": "603",
    "NJ": "201, 551, 609, 640, 732, 848, 856, 862, 908, 973",
    "NM": "505, 575, 957",
    "NY": "212, 315, 332, 347, 516, 518, 585, 607, 631, 646, 680, 716, 718, 838, 845, 914, 917, 929, 934",
    "NC": "252, 336, 472, 704, 743, 828, 910, 919, 980, 984",
    "ND": "701",
    "OH": "216, 220, 234, 283, 326, 330, 380, 419, 440, 513, 567, 614, 740, 937",
    "OK": "405, 539, 572, 580, 918",
    "OR": "458, 503, 541, 971",
    "PA": "215, 223, 267, 272, 412, 445, 484, 570, 610, 717, 724, 814, 835, 878",
    "RI": "401",
    "SC": "803, 839, 843, 854, 864",
    "SD": "605",
    "TN": "423, 615, 629, 731, 865, 901, 931",
    "TX": "210, 214, 254, 281, 325, 346, 361, 409, 430, 432, 469, 512, 682, 713, 726, 737, 806, 817, 830, 832, 903, 915, 936, 940, 956, 972, 979",
    "UT": "385, 435, 801",
    "VT": "802",
    "VA": "276, 434, 540, 571, 703, 757, 804, 948",
    "WA": "206, 253, 360, 425, 509, 564",
    "WV": "304, 681",
    "WI": "262, 414, 534, 608, 715, 920",
    "WY": "307",
}

AREA_CODE_TO_STATE = {
    area_code.strip(): state
    for state, area_codes in AREA_CODES_BY_STATE.items()
    for area_code in area_codes.split(",")
}


def _pct(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return float((Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ratio(numerator: int, denominator: int) -> float:
    if not denominator:
        return 0.0
    return float(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )


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


def _base_queryset(
    company: Company,
    start: datetime,
    end: datetime,
    *,
    team="",
    project="",
    preset="",
    closer_group="",
):
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
    closer_group = _clean_filter(closer_group)
    if team:
        qs = qs.filter(Q(team__name=team) | Q(team_name=team))
    if projects:
        project_filter = Q()
        for project_name in projects:
            project_filter |= Q(project_name__iexact=project_name)
        qs = qs.filter(project_filter)
    if preset:
        qs = qs.filter(preset=preset)
    if closer_group:
        qs = qs.filter(closer_group__iexact=closer_group)
    return qs


def _sale_metrics(qs):
    return qs.filter(disposition__iexact="SALE").aggregate(
        opportunities=Count("id"),
        sold_count=Count("id", filter=Q(sold=True)),
        transfers=Count("id"),
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
        if "agent_count" in item:
            item["agent_count"] = int(item.get("agent_count") or 0)
            item["kpi"] = _ratio(sold, item["agent_count"])
        result.append(item)
    return result


def _grouped(qs, fields, order_by="-sold_count", *, agent_count_qs=None):
    annotations = {
        "opportunities": Count("id"),
        "sold_count": Count("id", filter=Q(sold=True)),
        "transfers": Count("id"),
        "twenty_plus": Count("id", filter=Q(client_20_plus=True)),
        "thirty_plus": Count("id", filter=Q(client_30_plus=True)),
        "missing_preset": Count("id", filter=Q(preset__isnull=True) | Q(preset="")),
    }
    rows=(
        qs.filter(disposition__iexact="SALE")
        .values(*fields)
        .annotate(**annotations)
        .order_by(order_by, "-opportunities")[:250]
    )
    decorated = _decorate(rows)

    if agent_count_qs is not None:
        # Agent count is intentionally independent of SALE. It represents the
        # number of distinct VICIdial agents who disposed at least one real
        # (non-provisional, non-stale) call during the selected timeframe.
        # agent_user is the stable VICIdial identity; blank identities are not
        # counted because they cannot be deduplicated reliably.
        count_rows = (
            agent_count_qs.exclude(agent_user="")
            .values(*fields)
            .annotate(agent_count=Count("agent_user", distinct=True))
            .order_by()
        )
        counts = {
            tuple(row.get(field) for field in fields): int(row.get("agent_count") or 0)
            for row in count_rows
        }
        for item in decorated:
            key = tuple(item.get(field) for field in fields)
            agent_count = counts.get(key, 0)
            item["agent_count"] = agent_count
            item["kpi"] = _ratio(int(item.get("sold") or 0), agent_count)

    return decorated


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

        row["total_call_records"] = int(active.get("activity_count") or 0)
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
        sale_qs
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
        sale_qs
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
            "Conversion %": _pct(
                int(row.get("transfers") or 0),
                int(row.get("total_call_records") or 0),
            ),
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
            "Agent count": int(row.get("agent_count") or 0),
            "Sold": int(row.get("sold") or 0),
            "KPI": float(row.get("kpi") or 0),
            "30+": int(row.get("thirty_plus") or 0),
            "Transfers": int(row.get("transfers") or 0),
            "Conversion %": float(row.get("conversion_pct") or 0),
        }
        per_preset = transfer_counts.get(row["team"], {})
        for preset_name in presets:
            item[preset_name] = per_preset.get(preset_name, 0)
        rows.append(item)
    return rows


def _us_state_from_phone_number(phone_number: str | None) -> str | None:
    """Resolve a US state from a 10-digit NANP number using the configured area codes.

    Only plain 10-digit numbers and 11-digit numbers beginning with the US country
    code ``1`` are accepted. Anything else is deliberately left unmapped rather
    than guessing a geography.
    """
    digits = "".join(character for character in str(phone_number or "") if character.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return AREA_CODE_TO_STATE.get(digits[:3])


def _state_geography_rows(sale_qs):
    """Aggregate SALE dispositions and confirmed Sold calls by inferred US state."""
    by_state: dict[str, dict[str, int | str]] = {}
    rows = (
        sale_qs.exclude(phone_number__isnull=True)
        .exclude(phone_number="")
        .values_list("phone_number", "sold")
        .iterator(chunk_size=2000)
    )
    for phone_number, sold in rows:
        state = _us_state_from_phone_number(phone_number)
        if state is None:
            continue
        item = by_state.setdefault(
            state, {"state": state, "transfers": 0, "sold": 0}
        )
        item["transfers"] = int(item["transfers"]) + 1
        if sold:
            item["sold"] = int(item["sold"]) + 1
    return [by_state[state] for state in sorted(by_state)]


def _detail_row(event, *, include_sale_status: bool = False):
    team_name = (event.team.name if event.team_id else event.team_name) or "Unassigned"
    row = {
        "agent": event.agent_name or event.agent_user or "Unknown",
        "team": team_name,
        "number": event.phone_number or "",
        "client": event.preset or "Unresolved",
        "client_status": event.client_status or "",
        "disposition_time": event.analytics_at.isoformat() if getattr(event, "analytics_at", None) else "",
    }
    if include_sale_status:
        # Sold takes precedence over the 30+ opportunity state. Rows in this
        # table are either confirmed sales or unsold 30+ sale chances.
        row["sale_status"] = "Confirmed" if event.sold else "Only 30+"
        row["edited_at"] = event.edited_at.isoformat() if event.edited_at else ""
    return row


def _sold_detail_rows(qs):
    """Return confirmed sales plus unsold 30+ sale chances."""
    rows = []
    events = (
        qs.filter(disposition__iexact="SALE")
        .filter(Q(sold=True) | Q(client_30_plus=True))
        .select_related("team")
        .order_by("-analytics_at", "-received_at")[:500]
    )
    for event in events:
        rows.append(_detail_row(event, include_sale_status=True))
    return rows


def _transfer_detail_rows(qs):
    """Return SALE dispositions that are neither Sold nor 30+.

    The response key remains ``transfer_details`` for API compatibility, but
    the dashboard presents these rows as "Other SALE calls" because Transfers
    now means every SALE disposition, including Sold and 30+ rows.
    """
    rows = []
    events = (
        qs.filter(
            disposition__iexact="SALE",
            sold=False,
            client_30_plus=False,
        )
        .select_related("team")
        .order_by("-analytics_at", "-received_at")[:500]
    )
    for event in events:
        rows.append(_detail_row(event))
    return rows


def build_sales_dashboard(
    *,
    from_ms=None,
    to_ms=None,
    team="",
    project="",
    preset="",
    closer_group="",
):
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
    filters=(
        _clean_filter(team),
        _clean_multi_filter(project),
        _clean_filter(preset),
        _clean_filter(closer_group),
    )
    # Keep Redis/memcached keys bounded even when many projects are selected.
    filter_signature = hashlib.sha256(
        json.dumps(filters, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:20]
    cache_key=f"sales-analytics:v20:{company.pk}:{start_key}:{end_key}:{filter_signature}"
    cached=cache.get(cache_key)
    if cached is not None:
        return cached
    qs=_base_queryset(
        company,
        start,
        end,
        team=team,
        project=project,
        preset=preset,
        closer_group=closer_group,
    )
    # Leaderboard membership deliberately ignores the client/preset filter so
    # active agents remain visible with zero SALE metrics when appropriate.
    activity_qs=(
        _base_queryset(
            company,
            start,
            end,
            team=team,
            project=project,
            preset="",
            closer_group=closer_group,
        )
        .exclude(disposition__in=CallEvent.PROVISIONAL_START_DISPOSITIONS)
    )
    disposed_activity_qs = (
        activity_qs.filter(stale=False)
        .exclude(disposition__isnull=True)
        .exclude(disposition="")
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
    teams=_grouped(
        sale_qs,
        ["team__name", "team__team_leader__first_name", "team__team_leader__last_name"],
        agent_count_qs=disposed_activity_qs,
    )
    for row in teams:
        row["team"] = row.pop("team__name") or "Unassigned"
        first=row.pop("team__team_leader__first_name") or ""
        last=row.pop("team__team_leader__last_name") or ""
        row["team_leader"]=(f"{first} {last}".strip() or "Unassigned")
    presets=_grouped(sale_qs,["preset"])
    for row in presets:
        row["preset"] = row.get("preset") or "Unresolved"
    projects=_grouped(sale_qs,["project_name"], agent_count_qs=disposed_activity_qs)
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
            transfers=Count("id"),
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
    filter_cache=f"sales-analytics:filters:v3:{company.pk}:{start_key}:{end_key}"
    filter_values=cache.get(filter_cache)
    if filter_values is None:
        base=_base_queryset(company,start,end)
        filter_values={
            "teams": [{"text": value, "value": value} for value in sorted(set(base.exclude(team__name__isnull=True).exclude(team__name="").values_list("team__name",flat=True)))],
            "projects": [{"text": value, "value": value} for value in sorted(set(base.exclude(project_name__isnull=True).exclude(project_name="").values_list("project_name",flat=True)))],
            "presets": [{"text": value, "value": value} for value in sorted(set(base.filter(disposition__iexact="SALE").exclude(preset__isnull=True).exclude(preset="").values_list("preset",flat=True)))],
            "closer_groups": [{"text": value, "value": value} for value in sorted(set(base.exclude(closer_group__isnull=True).exclude(closer_group="").values_list("closer_group",flat=True)))],
        }
        cache.set(filter_cache,filter_values,300)
    sold_details = _sold_detail_rows(qs)
    transfer_details = _transfer_detail_rows(qs)
    state_geography = _state_geography_rows(sale_qs)
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
        "state_geography": state_geography,
        "state_transfer_heatmap": state_geography,
        "state_sold_heatmap": [row for row in state_geography if int(row["sold"]) > 0],
        "filters": filter_values,
    }
    cache.set(cache_key,payload,60)
    return payload
