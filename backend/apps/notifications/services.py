import hashlib

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import SystemNotification


def serialize_notification(notification, user=None) -> dict:
    return {
        "id": str(notification.pk),
        "category": notification.category,
        "severity": notification.severity,
        "title": notification.title,
        "message": notification.message,
        "branch_id": str(notification.branch_id) if notification.branch_id else None,
        "branch_name": notification.branch.name if notification.branch_id else "",
        "call_id": str(notification.call_id) if notification.call_id else None,
        "metadata": notification.metadata,
        "occurrences": notification.occurrences,
        "is_read": bool(user and notification.read_by.filter(pk=user.pk).exists()),
        "created_at": notification.created_at.isoformat(),
        "updated_at": notification.updated_at.isoformat(),
    }


def _broadcast(group: str, payload: dict) -> None:
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        group, {"type": "portal.notification", "payload": payload}
    )


def announce_call(event) -> None:
    payload = {
        "type": "call.received",
        "call": {
            "id": str(event.pk),
            "call_id": event.call_id,
            "campaign": event.campaign,
            "disposition": event.disposition,
        },
    }
    _broadcast(f"branch_{event.branch_id}", payload)
    _broadcast("system_admins", payload)


def _broadcast_notification(notification_id, event_type="notification.updated") -> None:
    notification = (
        SystemNotification.objects.select_related("branch", "call")
        .filter(pk=notification_id)
        .first()
    )
    if notification:
        _broadcast(
            "system_admins",
            {"type": event_type, "notification": serialize_notification(notification)},
        )


@transaction.atomic
def queue_unknown_team_notification(event, team_name: str) -> SystemNotification:
    normalized_name = " ".join(team_name.split()).casefold()
    digest = hashlib.sha256(
        f"{event.branch_id}:{normalized_name}".encode()
    ).hexdigest()[:40]
    dedupe_key = f"unknown-team:{digest}"
    now = timezone.now()
    metadata = {
        "team_name": team_name,
        "normalized_team_name": normalized_name,
        "latest_call_id": event.call_id,
        "latest_lead_id": event.lead_id,
        "agent_name": event.agent_name,
        "agent_user": event.agent_user,
    }
    notification, created = SystemNotification.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "category": SystemNotification.Category.UNKNOWN_TEAM,
            "severity": SystemNotification.Severity.WARNING,
            "title": f'Unknown team: {team_name}',
            "message": f'Calls for "{team_name}" are waiting for a team assignment in {event.branch.name}.',
            "branch": event.branch,
            "call": event,
            "metadata": metadata,
        },
    )
    if not created:
        notification = SystemNotification.objects.select_for_update().get(
            pk=notification.pk
        )
        SystemNotification.objects.filter(pk=notification.pk).update(
            occurrences=F("occurrences") + 1,
            call=event,
            metadata=metadata,
            message=f'Calls for "{team_name}" are waiting for a team assignment in {event.branch.name}.',
            resolved_at=None,
            updated_at=now,
        )
        notification.refresh_from_db()
        notification.read_by.clear()
    transaction.on_commit(lambda: _broadcast_notification(notification.pk))
    return notification


def resolve_unknown_team_notifications(team, aliases=()) -> int:
    normalized_names = {
        " ".join(value.split()).casefold() for value in (team.name, *aliases) if value
    }
    notification_ids = list(
        SystemNotification.objects.filter(
            category=SystemNotification.Category.UNKNOWN_TEAM,
            branch=team.branch,
            resolved_at__isnull=True,
            metadata__normalized_team_name__in=normalized_names,
        ).values_list("pk", flat=True)
    )
    if not notification_ids:
        return 0
    SystemNotification.objects.filter(pk__in=notification_ids).update(
        resolved_at=timezone.now(), updated_at=timezone.now()
    )
    for notification_id in notification_ids:
        transaction.on_commit(
            lambda notification_id=notification_id: _broadcast_notification(
                notification_id, "notification.resolved"
            )
        )
    return len(notification_ids)
