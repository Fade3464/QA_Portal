from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SystemNotification
from .services import serialize_notification


class IsSystemAdministrator(BasePermission):
    message = "System administrator access is required."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.is_active
            and request.user.is_superuser
        )


class NotificationListView(APIView):
    permission_classes = [IsSystemAdministrator]

    def get(self, request):
        notifications = list(
            SystemNotification.objects.filter(resolved_at__isnull=True)
            .select_related("branch", "call")[:50]
        )
        unread_ids = set(
            SystemNotification.objects.filter(
                pk__in=[item.pk for item in notifications], resolved_at__isnull=True
            )
            .exclude(read_by=request.user)
            .values_list("pk", flat=True)
        )
        payload = []
        for notification in notifications:
            item = serialize_notification(notification)
            item["is_read"] = notification.pk not in unread_ids
            payload.append(item)
        return Response({"unread_count": len(unread_ids), "results": payload})


class NotificationReadView(APIView):
    permission_classes = [IsSystemAdministrator]

    def post(self, request, pk):
        notification = SystemNotification.objects.filter(
            pk=pk, resolved_at__isnull=True
        ).first()
        if not notification:
            return Response(status=404)
        notification.read_by.add(request.user)
        return Response({"status": "read", "read_at": timezone.now().isoformat()})


class NotificationReadAllView(APIView):
    permission_classes = [IsSystemAdministrator]

    def post(self, request):
        notifications = SystemNotification.objects.filter(resolved_at__isnull=True)
        for notification in notifications.iterator(chunk_size=200):
            notification.read_by.add(request.user)
        return Response({"status": "read"})
