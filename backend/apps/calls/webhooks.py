from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.notifications.services import announce_call
from apps.tenancy.models import Dialer

from .models import CallEvent
from .services import event_key, parse_call_date, safe_int
from .tasks import resolve_recording


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
    key = event_key(event_type, payload)
    with transaction.atomic():
        event, created = CallEvent.objects.get_or_create(
            dialer=dialer,
            event_key=key,
            defaults={
                "branch": dialer.branch,
                "event_type": event_type,
                "call_id": payload.get("call_id", "")[:160],
                "unique_id": payload.get("uniqueid", "")[:160],
                "lead_id": payload.get("lead_id", "")[:80],
                "agent_log_id": payload.get("agent_log_id", "")[:80],
                "agent_user": payload.get("user", "")[:120],
                "campaign": payload.get("campaign", "")[:120],
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
            transaction.on_commit(lambda: resolve_recording.delay(str(event.pk)))
            transaction.on_commit(lambda: announce_call(event))
    return JsonResponse({"status": "OK", "event_id": str(event.pk), "created": created})
