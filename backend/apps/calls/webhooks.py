import re

from django.db import transaction
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.notifications.services import (
    announce_call,
    queue_unknown_team_notification,
)
from apps.tenancy.models import Dialer
from apps.tenancy.services import resolve_team_prefix

from .models import CallEvent
from .services import event_key, parse_call_date, safe_int
from .tasks import resolve_recording, resolve_sale_preset


TEAM_SEPARATOR = re.compile(r"\s*[-‐-‒–—]\s*", re.UNICODE)


def parse_agent_full_name(value: str) -> tuple[str, str]:
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


def infer_call_direction(
    closecallid: str | None,
    xfercallid: str | None,
    did_id: str | None,
    did_pattern: str | None,
    group: str | None,
) -> str:
    def clean(value: str | None) -> str:
        return (value or "").strip()

    closecallid = clean(closecallid)
    xfercallid = clean(xfercallid)
    did_id = clean(did_id)
    did_pattern = clean(did_pattern)
    group = clean(group)

    empty_values = {
        "0",
        "NULL",
        "NONE",
    }

    valid_closecall = bool(closecallid and closecallid.upper() not in empty_values)

    valid_xfercall = bool(xfercallid and xfercallid.upper() not in empty_values)

    has_did = bool(
        (did_id and did_id.upper() not in empty_values)
        or (did_pattern and did_pattern.upper() not in empty_values)
    )

    if valid_closecall and has_did:
        return CallEvent.Direction.INBOUND

    if valid_closecall and valid_xfercall:
        return CallEvent.Direction.TRANSFER

    if valid_closecall:
        return CallEvent.Direction.CLOSER

    return CallEvent.Direction.OUTBOUND


def infer_dial_method(
    call_id: str | None,
    call_direction: str,
) -> str:
    """
    Infer whether a VICIdial outbound call was manually dialed
    or auto-dialed.

    VICIdial manual-dial calls use an M-prefixed tracking call ID.

    Normal VICIdial auto-dial outbound calls normally use a
    V-prefixed call ID.

    We intentionally return UNKNOWN for any unexpected outbound
    call ID rather than incorrectly classifying it as AUTO.
    """

    call_id = (call_id or "").strip().upper()

    # Manual/auto classification is only relevant to an
    # outbound-originating call.
    if call_direction != CallEvent.Direction.OUTBOUND:
        return CallEvent.DialMethod.NOT_APPLICABLE

    if not call_id:
        return CallEvent.DialMethod.UNKNOWN

    # VICIdial manual dial
    if call_id.startswith("M"):
        return CallEvent.DialMethod.MANUAL

    # VICIdial standard auto-dial outbound call
    if call_id.startswith("V"):
        return CallEvent.DialMethod.AUTO

    # Do not guess for unusual/custom VICIdial call IDs.
    return CallEvent.DialMethod.UNKNOWN


@require_GET
def receive_vicidial(
    request,
    dialer_id,
    event_type,
):
    """Receive VICIdial Start Call and final disposition callbacks as one lifecycle.

    Start Call is stored canonically as ``NEW`` and is visible immediately, but it
    does not start recording/QA work. A later real disposition updates the same
    CallEvent. ``INCALL`` remains accepted only as a legacy provisional value.

    Idempotency is based on stable VICIdial call identifiers, not disposition or
    SQLdate, because both legitimately change during the lifecycle.
    """
    dialer = (
        Dialer.objects.select_related("branch")
        .filter(
            pk=dialer_id,
            is_active=True,
            branch__is_active=True,
            branch__company__is_active=True,
        )
        .first()
    )

    token = request.GET.get("token", "")
    if not dialer or not dialer.check_webhook_secret(token):
        return JsonResponse({"detail": "Invalid webhook credentials"}, status=403)

    if event_type not in {
        CallEvent.EventType.DISPOSITION,
        CallEvent.EventType.NO_AGENT,
    }:
        return JsonResponse({"detail": "Unsupported event type"}, status=404)

    payload = request.GET.dict()
    payload.pop("token", None)

    raw_disposition = payload.get("dispo") or payload.get("status") or ""
    normalized_disposition = raw_disposition.strip()
    # VICIdial campaigns may emit SQSAL/SMSAL for sale outcomes. Treat both as
    # canonical SALE before lifecycle classification so they follow the exact
    # same recording, preset-resolution, editor, and analytics workflow.
    if normalized_disposition.upper() in {"SQSAL", "SMSAL"}:
        normalized_disposition = "SALE"
    unresolved_placeholder = normalized_disposition.casefold() == "--a--dispo--b--"
    is_start_call = event_type == CallEvent.EventType.DISPOSITION and (
        not normalized_disposition
        or normalized_disposition.upper() in CallEvent.PROVISIONAL_START_DISPOSITIONS
        or unresolved_placeholder
    )
    disposition = (
        CallEvent.CANONICAL_START_DISPOSITION
        if is_start_call
        else normalized_disposition.upper()
    )

    team_name, agent_name = parse_agent_full_name(payload.get("agent_full_name", ""))
    team = resolve_team_prefix(dialer.branch, team_name) if team_name else None

    call_direction = infer_call_direction(
        payload.get("closecallid"),
        payload.get("xfercallid"),
        payload.get("did_id"),
        payload.get("did_pattern"),
        payload.get("group"),
    )
    dial_method = infer_dial_method(payload.get("call_id"), call_direction)

    ingestion_now = timezone.now()
    payload["dial_method"] = dial_method
    payload["call_direction"] = call_direction
    payload["disposition"] = disposition
    payload["ingestion_stage"] = "start" if is_start_call else "disposition"
    if is_start_call:
        payload["ingested_started_at"] = ingestion_now.isoformat()
    else:
        payload["ingested_finalized_at"] = ingestion_now.isoformat()

    key = event_key(event_type, payload)
    parsed_call_date = parse_call_date(payload.get("call_date"), reference=ingestion_now)

    values = {
        "branch": dialer.branch,
        "event_type": event_type,
        "call_id": payload.get("call_id", "")[:160],
        "close_call_id": payload.get("closecallid", "")[:160],
        "xfer_call_id": payload.get("xfercallid", "")[:160],
        "unique_id": payload.get("uniqueid", "")[:160],
        "lead_id": payload.get("lead_id", "")[:80],
        "agent_log_id": payload.get("agent_log_id", "")[:80],
        "agent_user": payload.get("user", "")[:120],
        "agent_name": agent_name,
        "team_name": team_name,
        "team": team,
        "campaign": payload.get("campaign", "")[:120],
        "closer_group": payload.get("group", "")[:120],
        "did_id": payload.get("did_id", "")[:80],
        "did_pattern": payload.get("did_pattern", "")[:160],
        "call_direction": call_direction,
        "dial_method": dial_method,
        "phone_number": payload.get("phone_number", "")[:40],
        "list_id": payload.get("list_id", "")[:80],
        "disposition": disposition[:40],
        "talk_time": safe_int(payload.get("talk_time")),
        "termination_reason": payload.get("term_reason", "")[:160],
        "source_recording_id": payload.get("recording_id", "")[:160],
        "source_recording_filename": payload.get("recording_filename", "")[:255],
        "call_date": parsed_call_date,
        "finalized_at": None if is_start_call else ingestion_now,
        "raw_payload": payload,
    }

    string_fields = (
        "call_id",
        "close_call_id",
        "xfer_call_id",
        "unique_id",
        "lead_id",
        "agent_log_id",
        "agent_user",
        "agent_name",
        "team_name",
        "campaign",
        "closer_group",
        "did_id",
        "did_pattern",
        "phone_number",
        "list_id",
        "termination_reason",
        "source_recording_id",
        "source_recording_filename",
    )

    def lifecycle_base():
        return CallEvent.objects.select_for_update().filter(
            dialer=dialer,
            event_type=event_type,
        )

    def strong_identity_match(base=None):
        """Match any already-known lifecycle by stable VICIdial identifiers."""
        base = base if base is not None else lifecycle_base()
        for field in ("call_id", "agent_log_id", "unique_id"):
            incoming = values[field]
            if incoming:
                match = base.filter(**{field: incoming}).order_by("-received_at").first()
                if match:
                    return match
        return None

    def pending_match():
        """Conservative fallback used only to attach a final Dispo to a pending row."""
        base = lifecycle_base().filter(
            Q(disposition__in=(*CallEvent.PROVISIONAL_START_DISPOSITIONS, "STALE"))
            | Q(stale=True)
        )
        match = strong_identity_match(base)
        if match:
            return match

        lead_id = values["lead_id"]
        agent_user = values["agent_user"]
        phone_number = values["phone_number"]
        if lead_id and agent_user:
            from datetime import timedelta

            query = base.filter(
                lead_id=lead_id,
                agent_user=agent_user,
                received_at__gte=timezone.now() - timedelta(hours=12),
            )
            if phone_number:
                query = query.filter(phone_number=phone_number)
            return query.order_by("-received_at").first()
        return None

    def merge_start(existing):
        """Apply a Start Call retry without ever downgrading a finalized row."""
        existing_payload = dict(existing.raw_payload or {})
        if existing.disposition.upper() in (
            *CallEvent.PROVISIONAL_START_DISPOSITIONS,
            "STALE",
        ) or existing.stale:
            existing_payload.update(payload)
        else:
            # Delayed Start Call after final Dispo: preserve authoritative final
            # values while still recording the server-side start receipt marker.
            start_payload = dict(payload)
            start_payload.update(existing_payload)
            start_payload["ingested_started_at"] = payload["ingested_started_at"]
            existing_payload = start_payload

        changed = ["raw_payload"]
        existing.raw_payload = existing_payload

        # Start Call retries may fill missing identifiers, but never replace
        # identifiers already attached to a finalized lifecycle.
        for field in string_fields:
            incoming = values[field]
            if incoming and not getattr(existing, field):
                setattr(existing, field, incoming)
                changed.append(field)

        if existing.team_id is None and values["team"] is not None:
            existing.team = values["team"]
            changed.append("team")
        if not existing.team_name and team_name:
            existing.team_name = team_name
            changed.append("team_name")

        # A delayed Start Call can improve a direct-final row's call start time.
        if parsed_call_date and (
            existing.call_date is None or parsed_call_date < existing.call_date
        ):
            existing.call_date = parsed_call_date
            changed.append("call_date")

        if (
            existing.disposition.upper() in CallEvent.PROVISIONAL_START_DISPOSITIONS
            and existing.disposition != CallEvent.CANONICAL_START_DISPOSITION
        ):
            existing.disposition = CallEvent.CANONICAL_START_DISPOSITION
            changed.append("disposition")

        existing.save(update_fields=list(dict.fromkeys(changed)))

    def merge_final(existing):
        """Apply an authoritative final callback idempotently to one lifecycle."""
        previous_disposition = (existing.disposition or "").upper()
        was_pending = (
            previous_disposition in CallEvent.PROVISIONAL_START_DISPOSITIONS
            or previous_disposition == "STALE"
            or existing.stale
        )
        recovered = existing.stale or previous_disposition == "STALE"

        merged_payload = dict(existing.raw_payload or {})
        merged_payload.update(payload)

        for field in string_fields:
            incoming = values[field]
            if incoming:
                setattr(existing, field, incoming)

        existing.branch = dialer.branch
        existing.event_type = event_type
        existing.team = values["team"] or existing.team
        existing.call_direction = call_direction
        existing.dial_method = dial_method
        existing.disposition = disposition[:40]

        if existing.disposition.upper() != "SALE":
            existing.client_20_plus = False
            existing.client_30_plus = False
            existing.sold = False
            existing.preset = None

        if payload.get("talk_time") not in (None, ""):
            existing.talk_time = values["talk_time"]

        # Start Call owns the canonical call start timestamp. A direct-final row
        # has no Start Call, so the final SQLdate is accepted only when empty.
        if existing.call_date is None:
            existing.call_date = parsed_call_date

        existing.raw_payload = merged_payload
        existing.stale = False
        if existing.finalized_at is None:
            existing.finalized_at = ingestion_now

        if was_pending:
            existing.recording_lookup_status = CallEvent.Status.PENDING
            existing.recording_download_status = CallEvent.Status.PENDING
            existing.recording_lookup_attempts = 0
            existing.recording_download_attempts = 0
            existing.recording_lookup_last_error = ""
            existing.recording_download_last_error = ""

        # Do not rewrite event_key on an already-existing row. Old rows may carry
        # the v1 key; strong-ID reconciliation keeps them compatible while all new
        # rows use the stable v2 key.
        existing.save()
        return was_pending, recovered

    created = False
    finalized_now = False
    recovered_from_stale = False

    with transaction.atomic():
        event = (
            CallEvent.objects.select_for_update()
            .filter(dialer=dialer, event_key=key)
            .first()
        )

        # Compatibility with rows created under the old mutable event-key scheme,
        # and resilience when VICIdial changes which strong ID is populated.
        if event is None:
            event = strong_identity_match()

        if event is None and not is_start_call and event_type == CallEvent.EventType.DISPOSITION:
            event = pending_match()

        if event is None:
            event, created = CallEvent.objects.get_or_create(
                dialer=dialer,
                event_key=key,
                defaults=values,
            )

        if created:
            if team_name and team is None:
                queue_unknown_team_notification(event, team_name)
            if is_start_call:
                transaction.on_commit(lambda: announce_call(event))
            else:
                finalized_now = True
        else:
            if is_start_call:
                merge_start(event)
            else:
                finalized_now, recovered_from_stale = merge_final(event)

        # Only a newly-created final call or an actual provisional/STALE -> final
        # transition may enter the post-disposition pipeline. Duplicate final
        # callbacks update metadata idempotently but never queue duplicate work.
        if finalized_now:
            transaction.on_commit(lambda: resolve_recording.delay(str(event.pk)))
            if event.disposition.upper() == "SALE":
                transaction.on_commit(lambda: resolve_sale_preset.delay(str(event.pk)))
            transaction.on_commit(lambda: announce_call(event))

    return JsonResponse(
        {
            "status": "OK",
            "event_id": str(event.pk),
            "created": created,
            "pending_disposition": is_start_call,
            "finalized": finalized_now,
            "recovered_from_stale": recovered_from_stale,
            "call_direction": call_direction,
            "dial_method": dial_method,
        }
    )
