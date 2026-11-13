from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.tenancy.models import Dialer, DialerFronterMapping


@dataclass(frozen=True)
class FronterCallMatch:
    call_date: datetime
    list_id: str
    phone_number: str


class InboundListLookupError(Exception):
    """Safe, user-visible failure raised by the inbound SALE list resolver."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.safe_message = " ".join(str(message or "lookup failed").split())[:220]
        self.retryable = retryable


def _api_params(dialer: Dialer, function: str, **extra) -> dict[str, str]:
    try:
        password = dialer.get_api_password()
    except ValidationError as exc:
        raise InboundListLookupError(
            "fronter API credentials unavailable"
        ) from exc

    if not dialer.api_url or not dialer.api_username or not password:
        raise InboundListLookupError("fronter API credentials unavailable")

    params = {
        # VICIdial documents source as a maximum of 20 characters.
        "source": (dialer.api_source or "qa_portal")[:20],
        "user": dialer.api_username,
        "pass": password,
        "function": function,
    }
    params.update(
        {
            key: str(value)
            for key, value in extra.items()
            if value not in (None, "")
        }
    )
    return params


def _api_get(dialer: Dialer, function: str, **extra) -> str:
    params = _api_params(dialer, function, **extra)
    try:
        with httpx.Client(
            timeout=dialer.request_timeout_seconds,
            follow_redirects=True,
            verify=True,
        ) as client:
            response = client.get(dialer.api_url, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        # Do not expose/log the HTTP exception text here because the request URL
        # contains the VICIdial API password as a query parameter.
        raise InboundListLookupError(
            "fronter API request failed", retryable=True
        ) from exc
    return response.text.strip()


def _phone_candidates(value: str) -> list[str]:
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return []
    candidates = [digits]
    # VICIdial installations commonly store NANPA numbers as either ten digits
    # or with the leading country code. phone_number_log accepts a comma-separated
    # set, so query both representations when it is unambiguous to do so.
    if len(digits) == 11 and digits.startswith("1"):
        candidates.append(digits[1:])
    return list(dict.fromkeys(candidates))


def _reference_in_fronter_timezone(event, fronter: Dialer) -> datetime:
    reference = event.call_date or event.finalized_at or event.received_at or timezone.now()
    if timezone.is_naive(reference):
        reference = timezone.make_aware(reference, timezone.get_current_timezone())
    return reference.astimezone(ZoneInfo(fronter.branch.timezone))


def _parse_phone_log(body: str) -> list[FronterCallMatch]:
    if not body:
        return []
    upper = body.lstrip().upper()
    if upper.startswith("ERROR:"):
        if "NO RECORDS FOUND" in upper:
            return []
        raise InboundListLookupError("fronter call lookup failed")

    rows: list[FronterCallMatch] = []
    for index, raw_line in enumerate(body.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if index == 0 and parts and parts[0].casefold() == "phone_number":
            continue
        if len(parts) < 3:
            continue
        try:
            call_date = datetime.strptime(parts[1][:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        list_id = parts[2]
        if not list_id:
            continue
        rows.append(
            FronterCallMatch(
                phone_number=parts[0],
                call_date=call_date,
                list_id=list_id,
            )
        )
    return rows


def _choose_call_for_date(
    rows: list[FronterCallMatch], *, target_date: date, reference_local: datetime
) -> FronterCallMatch | None:
    same_day = [row for row in rows if row.call_date.date() == target_date]
    if not same_day:
        return None

    reference_naive = reference_local.replace(tzinfo=None)
    at_or_before = [row for row in same_day if row.call_date <= reference_naive]
    pool = at_or_before or same_day
    return min(
        pool,
        key=lambda row: abs((reference_naive - row.call_date).total_seconds()),
    )


def _parse_list_name(body: str, expected_list_id: str) -> str:
    if not body:
        raise InboundListLookupError("list name lookup failed")
    if body.lstrip().upper().startswith("ERROR:"):
        raise InboundListLookupError("list name lookup failed")

    for index, raw_line in enumerate(body.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if index == 0 and parts and parts[0].casefold() == "list_id":
            continue
        if len(parts) < 2:
            continue
        if parts[0] == str(expected_list_id) and parts[1]:
            return parts[1][:255]
    raise InboundListLookupError("list name lookup failed")


def _mapping_for_ingroup(closer: Dialer, ingroup: str) -> DialerFronterMapping:
    target = " ".join((ingroup or "").split()).casefold()
    if not target:
        raise InboundListLookupError("closer in-group is missing")

    matches: list[DialerFronterMapping] = []
    mappings = (
        DialerFronterMapping.objects.select_related(
            "fronter_dialer",
            "fronter_dialer__branch",
            "fronter_dialer__branch__company",
        )
        .filter(
            closer_dialer=closer,
            fronter_dialer__is_active=True,
            fronter_dialer__branch__is_active=True,
            fronter_dialer__branch__company__is_active=True,
        )
        .order_by("created_at")
    )
    for mapping in mappings:
        if target in {name.casefold() for name in mapping.ingroup_names}:
            matches.append(mapping)

    if not matches:
        raise InboundListLookupError(
            f"no fronter mapping for in-group {ingroup}"
        )
    if len(matches) > 1:
        raise InboundListLookupError(
            f"in-group {ingroup} maps to multiple fronters"
        )
    return matches[0]


def lookup_inbound_sale_list_name(event) -> str:
    """Resolve the fronter list name that originated a closer SALE call.

    The closer call's in-group selects the configured fronter mapping. The
    mapped fronter's Non-Agent API is then searched for the same phone number on
    the call's local calendar date. When there are multiple calls that day, the
    closest call at-or-before the closer call is preferred. Finally list_info
    resolves the matching list ID to its human-readable list name.
    """
    closer = event.dialer
    if not closer.is_closer:
        raise InboundListLookupError("SALE did not originate on a closer dialer")
    if not event.phone_number:
        raise InboundListLookupError("phone number is missing")

    mapping = _mapping_for_ingroup(closer, event.closer_group)
    fronter = mapping.fronter_dialer
    phones = _phone_candidates(event.phone_number)
    if not phones:
        raise InboundListLookupError("phone number is missing")

    reference_local = _reference_in_fronter_timezone(event, fronter)
    target_date = reference_local.date()
    body = _api_get(
        fronter,
        "phone_number_log",
        stage="pipe",
        header="YES",
        detail="ALL",
        type="OUT",
        archived_lead="N",
        phone_number=",".join(phones),
    )
    matched = _choose_call_for_date(
        _parse_phone_log(body),
        target_date=target_date,
        reference_local=reference_local,
    )
    if matched is None:
        raise InboundListLookupError(
            f"no fronter call found for {target_date.isoformat()}",
            retryable=True,
        )
    if not matched.list_id.isdigit():
        raise InboundListLookupError("fronter call has no valid list ID")

    list_body = _api_get(
        fronter,
        "list_info",
        stage="pipe",
        header="YES",
        list_id=matched.list_id,
    )
    return _parse_list_name(list_body, matched.list_id)
