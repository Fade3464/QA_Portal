import re

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.notifications.services import (
    announce_call,
    queue_unknown_team_notification,
)
from apps.tenancy.models import Dialer
from apps.tenancy.services import resolve_team_prefix

from .models import CallEvent
from .services import event_key, parse_call_date, safe_int
from .tasks import resolve_recording


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
    # ---------------------------------------------------------
    # Resolve and authenticate dialer
    # ---------------------------------------------------------

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
        return JsonResponse(
            {
                "detail": "Invalid webhook credentials",
            },
            status=403,
        )

    # ---------------------------------------------------------
    # Validate event type
    # ---------------------------------------------------------

    if event_type not in {
        CallEvent.EventType.DISPOSITION,
        CallEvent.EventType.NO_AGENT,
    }:
        return JsonResponse(
            {
                "detail": "Unsupported event type",
            },
            status=404,
        )

    # ---------------------------------------------------------
    # Capture raw VICIdial payload
    # ---------------------------------------------------------

    payload = request.GET.dict()

    # Never persist the webhook secret in raw_payload.
    payload.pop("token", None)

    # ---------------------------------------------------------
    # Disposition
    # ---------------------------------------------------------

    disposition = payload.get("dispo") or payload.get("status") or ""

    # ---------------------------------------------------------
    # Agent/team parsing
    # ---------------------------------------------------------

    team_name, agent_name = parse_agent_full_name(payload.get("agent_full_name", ""))

    team = None

    if team_name:
        team = resolve_team_prefix(
            dialer.branch,
            team_name,
        )

    # ---------------------------------------------------------
    # Infer call direction
    # ---------------------------------------------------------

    call_direction = infer_call_direction(
        payload.get("closecallid"),
        payload.get("xfercallid"),
        payload.get("did_id"),
        payload.get("did_pattern"),
        payload.get("group"),
    )

    # ---------------------------------------------------------
    # Infer AUTO / MANUAL dialing
    # ---------------------------------------------------------

    dial_method = infer_dial_method(
        payload.get("call_id"),
        call_direction,
    )

    # Also preserve the derived value inside raw_payload.
    # This makes debugging particularly useful when comparing
    # VICIdial's original call_id against our classification.
    payload["dial_method"] = dial_method
    payload["call_direction"] = call_direction

    # ---------------------------------------------------------
    # Idempotency key
    # ---------------------------------------------------------

    key = event_key(
        event_type,
        payload,
    )

    # ---------------------------------------------------------
    # Create call event
    # ---------------------------------------------------------

    with transaction.atomic():
        event, created = CallEvent.objects.get_or_create(
            dialer=dialer,
            event_key=key,
            defaults={
                "branch": dialer.branch,
                "event_type": event_type,
                # -------------------------------------------------
                # VICIdial identifiers
                # -------------------------------------------------
                "call_id": payload.get(
                    "call_id",
                    "",
                )[:160],
                "close_call_id": payload.get(
                    "closecallid",
                    "",
                )[:160],
                "xfer_call_id": payload.get(
                    "xfercallid",
                    "",
                )[:160],
                "unique_id": payload.get(
                    "uniqueid",
                    "",
                )[:160],
                "lead_id": payload.get(
                    "lead_id",
                    "",
                )[:80],
                "agent_log_id": payload.get(
                    "agent_log_id",
                    "",
                )[:80],
                # -------------------------------------------------
                # Agent
                # -------------------------------------------------
                "agent_user": payload.get(
                    "user",
                    "",
                )[:120],
                "agent_name": agent_name,
                "team_name": team_name,
                "team": team,
                # -------------------------------------------------
                # Campaign / In-Group
                # -------------------------------------------------
                "campaign": payload.get(
                    "campaign",
                    "",
                )[:120],
                "closer_group": payload.get(
                    "group",
                    "",
                )[:120],
                # -------------------------------------------------
                # DID information
                # -------------------------------------------------
                "did_id": payload.get(
                    "did_id",
                    "",
                )[:80],
                "did_pattern": payload.get(
                    "did_pattern",
                    "",
                )[:160],
                # -------------------------------------------------
                # Derived call classification
                # -------------------------------------------------
                "call_direction": call_direction,
                "dial_method": dial_method,
                # -------------------------------------------------
                # Lead / phone information
                # -------------------------------------------------
                "phone_number": payload.get(
                    "phone_number",
                    "",
                )[:40],
                "list_id": payload.get(
                    "list_id",
                    "",
                )[:80],
                # -------------------------------------------------
                # Disposition
                # -------------------------------------------------
                "disposition": disposition[:40],
                "talk_time": safe_int(payload.get("talk_time")),
                "termination_reason": payload.get(
                    "term_reason",
                    "",
                )[:160],
                # -------------------------------------------------
                # Recording metadata from VICIdial
                # -------------------------------------------------
                "source_recording_id": payload.get(
                    "recording_id",
                    "",
                )[:160],
                "source_recording_filename": payload.get(
                    "recording_filename",
                    "",
                )[:255],
                # -------------------------------------------------
                # Call date
                # -------------------------------------------------
                "call_date": parse_call_date(payload.get("call_date")),
                # -------------------------------------------------
                # Full original/derived webhook payload
                # -------------------------------------------------
                "raw_payload": payload,
            },
        )

        if created:
            # -----------------------------------------------------
            # Unknown team warning
            # -----------------------------------------------------

            if team_name and team is None:
                queue_unknown_team_notification(
                    event,
                    team_name,
                )

            # -----------------------------------------------------
            # Recording processing
            #
            # This stays asynchronous so VICIdial gets its
            # HTTP response immediately.
            # -----------------------------------------------------

            transaction.on_commit(lambda: resolve_recording.delay(str(event.pk)))

            # -----------------------------------------------------
            # Portal notification
            # -----------------------------------------------------

            transaction.on_commit(lambda: announce_call(event))

    # ---------------------------------------------------------
    # Immediate response to VICIdial
    # ---------------------------------------------------------

    return JsonResponse(
        {
            "status": "OK",
            "event_id": str(event.pk),
            "created": created,
            "call_direction": call_direction,
            "dial_method": dial_method,
        }
    )
