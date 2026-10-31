from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from apps.tenancy.models import Dialer


TEAM_SEPARATOR = re.compile(r"\s*[-‐-‒–—]\s*", re.UNICODE)


@dataclass(frozen=True)
class StaleAgentIdentity:
    agent_user: str
    agent_full_name: str
    team_name: str
    agent_name: str


def parse_agent_full_name(value: str) -> tuple[str, str]:
    """Split the VICIdial full-name convention into team prefix and agent name."""
    cleaned = " ".join((value or "").split())

    if not cleaned:
        return "", ""

    pieces = TEAM_SEPARATOR.split(cleaned, maxsplit=1)

    if len(pieces) == 2 and pieces[0].strip() and pieces[1].strip():
        return (
            pieces[0].strip()[:160],
            pieces[1].strip()[:160],
        )

    return "", cleaned[:160]


def _api_params(dialer: Dialer, function: str, **extra) -> dict[str, str]:
    params = {
        "source": dialer.api_source,
        "user": dialer.api_username,
        "pass": dialer.get_api_password(),
        "function": function,
    }
    params.update({key: str(value) for key, value in extra.items() if value not in (None, "")})
    return params


def _recording_lookup_agent_user(dialer: Dialer, event) -> str:
    """Recover VICIdial agent user for a lead from recording_lookup when needed."""
    if not str(event.lead_id or "").isdigit():
        return ""

    occurred_at = event.call_date or event.received_at
    if occurred_at is None:
        return ""
    local_date = occurred_at.astimezone(ZoneInfo(dialer.branch.timezone)).date().isoformat()

    params = _api_params(
        dialer,
        "recording_lookup",
        stage="pipe",
        header="NO",
        duration="Y",
        lead_id=event.lead_id,
        date=local_date,
        uniqueid=event.unique_id,
    )
    with httpx.Client(
        timeout=dialer.request_timeout_seconds,
        follow_redirects=True,
        verify=True,
    ) as client:
        response = client.get(dialer.api_url, params=params)
        response.raise_for_status()

    body = response.text.strip()
    if not body or body.upper().startswith("ERROR:"):
        return ""

    target = occurred_at.astimezone(ZoneInfo(dialer.branch.timezone)).replace(tzinfo=None)
    candidates: list[tuple[float, str]] = []
    for raw_line in body.splitlines():
        parts = [part.strip() for part in raw_line.split("|")]
        if len(parts) < 4 or parts[3] != str(event.lead_id):
            continue
        agent_user = parts[1][:120]
        if not agent_user:
            continue
        try:
            started_at = datetime.strptime(parts[0][:19], "%Y-%m-%d %H:%M:%S")
            distance = abs((started_at - target).total_seconds())
        except ValueError:
            distance = float("inf")
        candidates.append((distance, agent_user))

    if not candidates:
        return ""
    return min(candidates, key=lambda item: item[0])[1]


def _agent_full_name(dialer: Dialer, agent_user: str) -> str:
    """Fetch a logged-in VICIdial user's full name through agent_ingroup_info."""
    if not agent_user:
        return ""

    params = _api_params(
        dialer,
        "agent_ingroup_info",
        stage="info",
        agent_user=agent_user,
    )
    with httpx.Client(
        timeout=dialer.request_timeout_seconds,
        follow_redirects=True,
        verify=True,
    ) as client:
        response = client.get(dialer.api_url, params=params)
        response.raise_for_status()

    body = response.text
    if not body.strip() or body.lstrip().upper().startswith("ERROR:"):
        return ""

    # VICIdial's info stage renders: "Agent: <user> - <full_name>" followed by
    # the Campaign cell. Strip tags first so minor HTML formatting differences
    # do not make identity parsing brittle.
    plain = html.unescape(re.sub(r"<[^>]+>", " ", body))
    plain = " ".join(plain.split())
    pattern = re.compile(
        rf"\bAgent:\s*{re.escape(agent_user)}\s*-\s*(.*?)\s+(?:Campaign:|Close\b|$)",
        re.IGNORECASE,
    )
    match = pattern.search(plain)
    if not match:
        return ""
    return " ".join(match.group(1).split())[:160]


def lookup_stale_agent_identity(dialer: Dialer, event) -> StaleAgentIdentity | None:
    """Recover missing stale-call identity through VICIdial's Non-Agent API.

    Start Call usually supplies ``user`` even when ``agent_full_name`` is empty.
    If ``user`` is absent too, recording_lookup is used first to recover it from
    the lead. agent_ingroup_info then supplies the VICIdial full name, which is
    parsed using the same Team - Agent convention as webhook ingestion.
    """
    agent_user = (event.agent_user or "").strip()
    if not agent_user:
        agent_user = _recording_lookup_agent_user(dialer, event)
    if not agent_user:
        return None

    full_name = _agent_full_name(dialer, agent_user)
    if not full_name:
        return None

    team_name, agent_name = parse_agent_full_name(full_name)
    return StaleAgentIdentity(
        agent_user=agent_user[:120],
        agent_full_name=full_name[:160],
        team_name=team_name[:160],
        agent_name=agent_name[:160],
    )
