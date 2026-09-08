import re

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.notifications.services import announce_call, queue_unknown_team_notification
from apps.tenancy.models import Dialer
from apps.tenancy.services import resolve_team_prefix

from .models import CallEvent
from .services import event_key, parse_call_date, safe_int
from .tasks import resolve_recording


TEAM_SEPARATOR = re.compile(r"\s*[-‐‑‒–—]\s*", re.UNICODE)


def parse_agent_full_name(value: str) -> tuple[str, str]:
    cleaned = " ".join((value or "").split())
    if not cleaned:
        return "", ""
    pieces = TEAM_SEPARATOR.split(cleaned, maxsplit=1)
    if len(pieces) == 2 and pieces[0].strip() and pieces[1].strip():
        return pieces[0].strip()[:160], pieces[1].strip()[:160]
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

    empty_values = {"0", "NULL", "NONE"}
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


@require_GET
def receive_vicidial(request, dialer_id, event_type):
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
    disposition = payload.get("dispo") or payload.get("status") or ""
    team_name, agent_name = parse_agent_full_name(payload.get("agent_full_name", ""))
    team = None
    if team_name:
        team = resolve_team_prefix(dialer.branch, team_name)
    key = event_key(event_type, payload)
    with transaction.atomic():
        event, created = CallEvent.objects.get_or_create(
            dialer=dialer,
            event_key=key,
            defaults={
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
                "call_direction": infer_call_direction(
                    payload.get("closecallid"),
                    payload.get("xfercallid"),
                    payload.get("did_id"),
                    payload.get("did_pattern"),
                    payload.get("group"),
                ),
                "phone_number": payload.get("phone_number", "")[:40],
                "list_id": payload.get("list_id", "")[:80],
                "disposition": disposition[:40],
                "talk_time": safe_int(payload.get("talk_time")),
                "termination_reason": payload.get("term_reason", "")[:160],
                "source_recording_id": payload.get("recording_id", "")[:160],
                "source_recording_filename": payload.get("recording_filename", "")[
                    :255
                ],
                "call_date": parse_call_date(payload.get("call_date")),
                "raw_payload": payload,
            },
        )
        if created:
            if team_name and team is None:
                queue_unknown_team_notification(event, team_name)
            transaction.on_commit(lambda: resolve_recording.delay(str(event.pk)))
            transaction.on_commit(lambda: announce_call(event))
    return JsonResponse({"status": "OK", "event_id": str(event.pk), "created": created})
