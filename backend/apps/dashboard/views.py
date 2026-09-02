from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.calls.models import CallEvent, Review
from apps.calls.serializers import CallEventSerializer
from apps.calls.views import scoped_calls


def health(request):
    return JsonResponse({"status": "ok"})


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        calls = scoped_calls(request.user)
        since = timezone.now() - timedelta(hours=24)
        recent = calls.filter(received_at__gte=since)
        review_scope = Review.objects.filter(call__in=calls)
        metrics = recent.aggregate(
            total_calls=Count("id"),
            recordings_ready=Count(
                "id", filter=Q(recording_download_status=CallEvent.Status.DOWNLOADED)
            ),
            recordings_pending=Count(
                "id",
                filter=Q(
                    recording_download_status__in=[
                        CallEvent.Status.PENDING,
                        CallEvent.Status.RETRYING,
                        CallEvent.Status.DOWNLOADING,
                    ]
                ),
            ),
            avg_talk_time=Avg("talk_time"),
        )
        completed = review_scope.filter(status=Review.Status.COMPLETED).count()
        assigned = review_scope.count()
        return Response(
            {
                "metrics": {
                    **metrics,
                    "reviewed": completed,
                    "review_completion": round((completed / assigned * 100), 1)
                    if assigned
                    else 0,
                },
                "recent_calls": CallEventSerializer(recent[:6], many=True).data,
                "generated_at": timezone.now(),
            }
        )
