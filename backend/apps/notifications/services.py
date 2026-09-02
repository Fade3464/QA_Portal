from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


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
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"branch_{event.branch_id}", {"type": "portal.notification", "payload": payload}
    )
    async_to_sync(channel_layer.group_send)(
        "system_admins", {"type": "portal.notification", "payload": payload}
    )
