from pathlib import Path

from django.http import FileResponse, Http404
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from .models import CallEvent
from .serializers import CallEventSerializer


def scoped_calls(user):
    queryset = CallEvent.objects.select_related("dialer", "branch")
    return queryset if user.is_superuser else queryset.filter(branch_id=user.branch_id)


class CallListView(ListAPIView):
    serializer_class = CallEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = scoped_calls(self.request.user)
        if status := self.request.query_params.get("recording_status"):
            queryset = queryset.filter(recording_download_status=status)
        if campaign := self.request.query_params.get("campaign"):
            queryset = queryset.filter(campaign=campaign)
        return queryset[:100]


class RecordingView(ListAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        event = (
            scoped_calls(request.user)
            .filter(pk=pk, recording_download_status=CallEvent.Status.DOWNLOADED)
            .first()
        )
        if not event or not event.recording_path:
            raise Http404
        path = Path(event.recording_path)
        if not path.is_file():
            raise Http404
        return FileResponse(path.open("rb"), as_attachment=False, filename=path.name)
