from django.db.models import Q
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SystemNotification
from .services import serialize_notification


def scoped_notifications(user):
    queryset = SystemNotification.objects.filter(resolved_at__isnull=True)
    if user.is_superuser:
        return queryset.filter(
            ~Q(category=SystemNotification.Category.CUSTOM) | Q(recipients=user)
        ).distinct()
    return queryset.filter(recipients=user)


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = list(
            scoped_notifications(request.user).select_related("branch", "call")[:50]
        )
        unread_ids = set(
            scoped_notifications(request.user)
            .filter(
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
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notification = scoped_notifications(request.user).filter(pk=pk).first()
        if not notification:
            return Response(status=404)
        notification.read_by.add(request.user)
        return Response({"status": "read", "read_at": timezone.now().isoformat()})


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        notifications = scoped_notifications(request.user)
        for notification in notifications.iterator(chunk_size=200):
            notification.read_by.add(request.user)
        return Response({"status": "read"})
