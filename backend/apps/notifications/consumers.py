from datetime import timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from apps.accounts.models import User
from apps.calls.models import AnalysisPresence, CallEvent


PRESENCE_TTL_SECONDS = 45


@database_sync_to_async
def _can_analyze(user, call_id):
    if not user.is_active or user.is_superuser or user.role != User.Role.QA:
        return False
    from apps.calls.views import scoped_calls

    return (
        scoped_calls(user)
        .filter(
            pk=call_id,
            recording_download_status=CallEvent.Status.DOWNLOADED,
        )
        .exclude(recording_path="")
        .exists()
    )


@database_sync_to_async
def _touch_presence(call_id, user, channel_name):
    AnalysisPresence.objects.update_or_create(
        channel_name=channel_name,
        defaults={"call_id": call_id, "user": user},
    )


@database_sync_to_async
def _remove_presence(channel_name):
    AnalysisPresence.objects.filter(channel_name=channel_name).delete()


@database_sync_to_async
def _presence_roster(call_id):
    cutoff = timezone.now() - timedelta(seconds=PRESENCE_TTL_SECONDS)
    AnalysisPresence.objects.filter(last_seen_at__lt=cutoff).delete()
    viewers = (
        AnalysisPresence.objects.filter(call_id=call_id, last_seen_at__gte=cutoff)
        .values("user_id", "user__first_name", "user__last_name", "user__email")
        .order_by("user__first_name", "user__last_name", "user__email")
        .distinct()
    )
    return [
        {
            "id": str(viewer["user_id"]),
            "name": " ".join(
                filter(
                    None,
                    (viewer["user__first_name"], viewer["user__last_name"]),
                )
            )
            or viewer["user__email"],
        }
        for viewer in viewers
    ]


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group_names = [f"user_{user.pk}"]
        if user.is_superuser:
            self.group_names.append("system_admins")
        elif user.branch_id:
            self.group_names.append(f"branch_{user.branch_id}")
        for group_name in self.group_names:
            await self.channel_layer.group_add(group_name, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connected", "message": "Live updates connected"})

    async def disconnect(self, close_code):
        for group_name in getattr(self, "group_names", []):
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def portal_notification(self, event):
        await self.send_json(event["payload"])


class AnalysisPresenceConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.call_id = self.scope["url_route"]["kwargs"]["call_id"]
        self.group_name = f"analysis_{self.call_id}"
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4401)
            return
        if not await _can_analyze(user, self.call_id):
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await _touch_presence(self.call_id, user, self.channel_name)
        await self.accept()
        await self._broadcast_presence()

    async def disconnect(self, close_code):
        if not hasattr(self, "group_name"):
            return
        await _remove_presence(self.channel_name)
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await self._broadcast_presence()

    async def receive_json(self, content, **kwargs):
        if content.get("type") != "presence.heartbeat":
            return
        await _touch_presence(self.call_id, self.scope["user"], self.channel_name)
        await self._broadcast_presence()

    async def _broadcast_presence(self):
        viewers = await _presence_roster(self.call_id)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "analysis.event",
                "payload": {"type": "presence.updated", "viewers": viewers},
            },
        )

    async def analysis_event(self, event):
        await self.send_json(event["payload"])
