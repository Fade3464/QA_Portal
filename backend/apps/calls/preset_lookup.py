from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
import re
from zoneinfo import ZoneInfo

import httpx
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.tenancy.models import Dialer


@dataclass(frozen=True)
class PresetLookupResult:
    preset: str
    occurred_at: datetime
    dialed: str


class _TableParser(HTMLParser):
    """Small dependency-free HTML table parser for VICIdial user_stats.php."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
        elif self._table_depth == 1 and tag == "tr":
            self._row = []
        elif self._table_depth == 1 and tag in {"td", "th"}:
            self._cell_parts = []
        elif self._table_depth == 1 and tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_data(self, data):
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._table_depth == 1 and tag in {"td", "th"} and self._cell_parts is not None:
            value = " ".join("".join(self._cell_parts).split())
            if self._row is not None:
                self._row.append(value)
            self._cell_parts = None
        elif self._table_depth == 1 and tag == "tr":
            if self._row is not None and self._rows is not None and any(self._row):
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table_depth:
            if self._table_depth == 1 and self._rows is not None:
                self.tables.append(self._rows)
                self._rows = None
            self._table_depth -= 1


def _manual_outbound_rows(html: str) -> list[dict[str, str]]:
    section = re.search(
        r"Manual\s+Outbound\s+Calls\s+for\s+this\s+Time\s+Period:.*?<table\b[^>]*>(.*?)</table>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not section:
        return []
    parser = _TableParser()
    parser.feed(f"<table>{section.group(1)}</table>")
    required = {"DATE/TIME", "CALL TYPE", "LEAD", "PRESET"}
    for table in parser.tables:
        if not table:
            continue
        header = [cell.strip().upper() for cell in table[0]]
        if not required.issubset(set(header)):
            continue
        index = {name: header.index(name) for name in required}
        if "DIALED" in header:
            index["DIALED"] = header.index("DIALED")
        rows: list[dict[str, str]] = []
        for cells in table[1:]:
            if len(cells) <= max(index.values()):
                continue
            rows.append({name: cells[position].strip() for name, position in index.items()})
        return rows
    return []


def parse_latest_preset(
    html: str,
    *,
    lead_id: str,
    window_start: datetime | None,
    window_end: datetime,
    timezone_name: str,
) -> PresetLookupResult | None:
    zone = ZoneInfo(timezone_name)
    start_local = window_start.astimezone(zone) if window_start else None
    end_local = window_end.astimezone(zone)
    # Allow small clock/report skew around both boundaries.
    lower = start_local - timedelta(minutes=5) if start_local else None
    upper = end_local + timedelta(minutes=5)

    candidates: list[PresetLookupResult] = []
    for row in _manual_outbound_rows(html):
        if row.get("CALL TYPE", "").strip().upper() != "XFER_3WAY":
            continue
        if row.get("LEAD", "").strip() != str(lead_id).strip():
            continue
        preset = row.get("PRESET", "").strip()
        if not preset:
            continue
        try:
            occurred_naive = datetime.strptime(row.get("DATE/TIME", "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        occurred = occurred_naive.replace(tzinfo=zone)
        if lower and occurred < lower:
            continue
        if occurred > upper:
            continue
        candidates.append(
            PresetLookupResult(
                preset=preset[:160],
                occurred_at=occurred,
                dialed=row.get("DIALED", "")[:255],
            )
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.occurred_at)


def lookup_sale_preset(dialer: Dialer, event) -> PresetLookupResult | None:
    if not dialer.has_preset_lookup_config:
        raise ValidationError("Preset lookup credentials are not configured for this dialer.")
    if not event.agent_user or not event.lead_id:
        raise ValidationError("Preset lookup requires both agent user and lead ID.")

    zone = ZoneInfo(dialer.branch.timezone)
    raw_payload = event.raw_payload or {}
    finalized_at = parse_datetime(str(raw_payload.get("ingested_finalized_at", "")))
    if finalized_at is None:
        finalized_at = timezone.now()
    if timezone.is_naive(finalized_at):
        finalized_at = timezone.make_aware(finalized_at, timezone.get_current_timezone())

    started_at = parse_datetime(str(raw_payload.get("ingested_started_at", "")))
    if started_at is not None and timezone.is_naive(started_at):
        started_at = timezone.make_aware(started_at, timezone.get_current_timezone())

    if started_at is None:
        # Final-only deployments do not have a Start Call ingestion timestamp.
        # Use the earliest sensible bound from the call timestamp and talk time
        # so long SALE calls do not lose an earlier XFER_3WAY row.
        fallback_start = finalized_at - timedelta(seconds=max(0, event.talk_time or 0))
        if event.call_date is not None:
            started_at = min(event.call_date, fallback_start)
        else:
            started_at = fallback_start

    local_start = started_at.astimezone(zone)
    local_end = finalized_at.astimezone(zone)
    params = {
        "user": event.agent_user,
        "begin_date": local_start.date().isoformat(),
        "end_date": local_end.date().isoformat(),
        "submit": "submit",
    }
    auth = httpx.BasicAuth(
        dialer.preset_lookup_username,
        dialer.get_preset_lookup_password(),
    )
    with httpx.Client(
        timeout=dialer.request_timeout_seconds,
        follow_redirects=True,
        verify=dialer.preset_lookup_verify_tls,
        auth=auth,
    ) as client:
        response = client.get(dialer.preset_lookup_url, params=params)
        response.raise_for_status()

    return parse_latest_preset(
        response.text,
        lead_id=event.lead_id,
        window_start=started_at,
        window_end=finalized_at,
        timezone_name=dialer.branch.timezone,
    )
