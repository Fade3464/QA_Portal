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
    """Receive both VICIdial Start Call and final disposition callbacks.

    The same ``dispo`` webhook URL can be configured in both VICIdial fields.
    Start Call callbacks are stored canonically as ``NEW`` and deliberately do
    not start recording/QA processing. ``INCALL`` remains accepted as a legacy
    provisional value. A later real disposition updates the same canonical row
    and starts the existing post-disposition pipeline.
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

    payload["dial_method"] = dial_method
    payload["call_direction"] = call_direction
    payload["disposition"] = disposition
    payload["ingestion_stage"] = "start" if is_start_call else "disposition"
    ingestion_now = timezone.now()
    if is_start_call:
        # Keep a server-side lifecycle lower bound that cannot be distorted by
        # provider-specific SQLdate semantics on the later Dispo callback.
        payload["ingested_started_at"] = ingestion_now.isoformat()
    else:
        # Preserve the actual final callback time even when this disposition
        # updates a row originally created by Start Call URL. Preset lookup uses
        # this timestamp to avoid matching a later transfer on the same lead.
        payload["ingested_finalized_at"] = ingestion_now.isoformat()

    key = event_key(event_type, payload)
    parsed_call_date = parse_call_date(payload.get("call_date"))

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
        "raw_payload": payload,
    }

    def pending_match_queryset():
        """Find the provisional/stale version of this call, strongest IDs first."""
        base = (
            CallEvent.objects.select_for_update()
            .filter(
                dialer=dialer,
                event_type=CallEvent.EventType.DISPOSITION,
            )
            .filter(
                Q(disposition__in=(*CallEvent.PROVISIONAL_START_DISPOSITIONS, "STALE"))
                | Q(stale=True)
            )
        )
        unique_id = values["unique_id"]
        call_id = values["call_id"]
        agent_log_id = values["agent_log_id"]
        lead_id = values["lead_id"]
        agent_user = values["agent_user"]

        if unique_id:
            match = base.filter(unique_id=unique_id).order_by("-received_at").first()
            if match:
                return match
        if call_id:
            match = base.filter(call_id=call_id).order_by("-received_at").first()
            if match:
                return match
        if agent_log_id:
            match = base.filter(agent_log_id=agent_log_id).order_by("-received_at").first()
            if match:
                return match
        if lead_id and agent_user:
            # Fallback only when VICIdial omitted stronger IDs. Bound the search
            # so an old stale attempt for the same lead/agent cannot be revived.
            from django.utils import timezone
            from datetime import timedelta

            return (
                base.filter(
                    lead_id=lead_id,
                    agent_user=agent_user,
                    received_at__gte=timezone.now() - timedelta(hours=12),
                )
                .order_by("-received_at")
                .first()
            )
        return None

    created = False
    finalized_now = False
    recovered_from_stale = False

    with transaction.atomic():
        event = (
            CallEvent.objects.select_for_update()
            .filter(dialer=dialer, event_key=key)
            .first()
        )

        if event is None and is_start_call and event_type == CallEvent.EventType.DISPOSITION:
            # A delayed/retried Start Call callback must never create a second
            # provisional row after the real disposition has already finalized the
            # call. Only use strong VICIdial identifiers for this guard.
            existing = CallEvent.objects.select_for_update().filter(
                dialer=dialer,
                event_type=CallEvent.EventType.DISPOSITION,
            )
            if values["unique_id"]:
                event = existing.filter(unique_id=values["unique_id"]).order_by("-received_at").first()
            if event is None and values["call_id"]:
                event = existing.filter(call_id=values["call_id"]).order_by("-received_at").first()
            if event is None and values["agent_log_id"]:
                event = existing.filter(agent_log_id=values["agent_log_id"]).order_by("-received_at").first()

        if event is None and not is_start_call and event_type == CallEvent.EventType.DISPOSITION:
            event = pending_match_queryset()
            if event is not None:
                recovered_from_stale = event.stale or event.disposition == "STALE"
                # Preserve any future manually-maintained business fields such
                # as sold/client_status while refreshing dialer-owned metadata.
                merged_payload = dict(event.raw_payload or {})
                merged_payload.update(payload)
                values["raw_payload"] = merged_payload

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
                for field in string_fields:
                    incoming = values[field]
                    if incoming:
                        setattr(event, field, incoming)

                event.branch = dialer.branch
                event.event_type = event_type
                event.event_key = key
                event.team = values["team"] or event.team
                event.call_direction = call_direction
                event.dial_method = dial_method
                event.disposition = disposition[:40]
                # A real late disposition is authoritative for dialer status.
                # If it is not SALE, any manually-entered SALE-only business
                # fields must be cleared to keep the row internally consistent.
                if event.disposition.upper() != "SALE":
                    event.client_20_plus = False
                    event.client_30_plus = False
                    event.sold = False
                    event.preset = None
                if payload.get("talk_time") not in (None, ""):
                    event.talk_time = values["talk_time"]
                # Start Call URL is the best source for the canonical call
                # start timestamp. Do not overwrite it with a provider-specific
                # final SQLdate value when the Dispo callback arrives.
                if event.call_date is None:
                    event.call_date = parsed_call_date
                event.raw_payload = values["raw_payload"]
                event.stale = False
                # A stale row had recording processing explicitly skipped. A
                # real disposition makes it eligible for the normal pipeline.
                event.recording_lookup_status = CallEvent.Status.PENDING
                event.recording_download_status = CallEvent.Status.PENDING
                event.recording_lookup_attempts = 0
                event.recording_download_attempts = 0
                event.recording_lookup_last_error = ""
                event.recording_download_last_error = ""
                event.save()
                finalized_now = True

        if event is None:
            event, created = CallEvent.objects.get_or_create(
                dialer=dialer,
                event_key=key,
                defaults=values,
            )
            finalized_now = created and not is_start_call

        if created and team_name and team is None:
            queue_unknown_team_notification(event, team_name)

        # Start Call URL records are visible in the call library immediately,
        # but intentionally stop before recording lookup and QA processing.
        if created and is_start_call:
            transaction.on_commit(lambda: announce_call(event))

        # Only a newly-created final call or a provisional/STALE row that was just
        # finalized may enter the existing post-disposition pipeline.
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
