import mimetypes
import re
from pathlib import Path

from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import content_disposition_header
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CallEvent
from .serializers import CallEventSerializer


def scoped_calls(user):
    queryset = CallEvent.objects.select_related("dialer", "branch", "team")
    return queryset if user.is_superuser else queryset.filter(branch_id=user.branch_id)


class CallPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CallListView(ListAPIView):
    serializer_class = CallEventSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CallPagination

    def _values(self, name, *, allowed=None):
        values = []
        for raw_value in self.request.query_params.getlist(name):
            values.append(raw_value.strip())
        values = list(dict.fromkeys(value for value in values if value))
        if len(values) > 50 or any(len(value) > 160 for value in values):
            raise ValidationError({name: "Too many or excessively long filter values."})
        if allowed is not None:
            invalid = set(values) - set(allowed)
            if invalid:
                raise ValidationError({name: f"Unsupported value: {sorted(invalid)[0]}"})
        return values

    def _non_negative_int(self, name):
        value = self.request.query_params.get(name)
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValidationError({name: "Enter a whole number."}) from error
        if parsed < 0 or parsed > 2_147_483_647:
            raise ValidationError({name: "Enter a number between 0 and 2147483647."})
        return parsed

    def _datetime(self, name):
        value = self.request.query_params.get(name)
        if not value:
            return None
        parsed = parse_datetime(value)
        if parsed is None:
            raise ValidationError({name: "Enter a valid ISO 8601 date and time."})
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def get_queryset(self):
        queryset = scoped_calls(self.request.user)
        search = self.request.query_params.get("search", "").strip()
        if len(search) > 200:
            raise ValidationError({"search": "Search cannot exceed 200 characters."})
        if search:
            queryset = queryset.filter(
                Q(call_id__icontains=search)
                | Q(unique_id__icontains=search)
                | Q(lead_id__icontains=search)
                | Q(agent_log_id__icontains=search)
                | Q(agent_user__icontains=search)
                | Q(agent_name__icontains=search)
                | Q(team_name__icontains=search)
                | Q(team__name__icontains=search)
                | Q(campaign__icontains=search)
                | Q(phone_number__icontains=search)
                | Q(disposition__icontains=search)
                | Q(source_recording_id__icontains=search)
                | Q(source_recording_filename__icontains=search)
            )

        agent_values = self._values("agent")
        if agent_values:
            queryset = queryset.filter(
                Q(agent_name__in=agent_values)
                | Q(agent_name="", agent_user__in=agent_values)
            )

        team_values = self._values("team")
        if team_values:
            team_query = Q()
            for value in team_values:
                team_query |= Q(team_name__iexact=value) | Q(team__name__iexact=value)
            queryset = queryset.filter(team_query)

        dimension_filters = {
            "campaign": "campaign__in",
            "disposition": "disposition__in",
            "dialer": "dialer__name__in",
        }
        for parameter, lookup in dimension_filters.items():
            if values := self._values(parameter):
                queryset = queryset.filter(**{lookup: values})

        if event_types := self._values(
            "event_type", allowed=CallEvent.EventType.values
        ):
            queryset = queryset.filter(event_type__in=event_types)
        if recording_statuses := self._values(
            "recording_status", allowed=CallEvent.Status.values
        ):
            queryset = queryset.filter(
                recording_download_status__in=recording_statuses
            )

        date_field = self.request.query_params.get("date_field", "received_at")
        if date_field not in {"received_at", "call_date"}:
            raise ValidationError({"date_field": "Unsupported date field."})
        date_from = self._datetime("date_from")
        date_to = self._datetime("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError({"date_to": "End time must be after start time."})
        if date_from:
            queryset = queryset.filter(**{f"{date_field}__gte": date_from})
        if date_to:
            queryset = queryset.filter(**{f"{date_field}__lte": date_to})

        talk_time_min = self._non_negative_int("talk_time_min")
        talk_time_max = self._non_negative_int("talk_time_max")
        if (
            talk_time_min is not None
            and talk_time_max is not None
            and talk_time_min > talk_time_max
        ):
            raise ValidationError(
                {"talk_time_max": "Maximum talk time must be at least the minimum."}
            )
        if talk_time_min is not None:
            queryset = queryset.filter(talk_time__gte=talk_time_min)
        if talk_time_max is not None:
            queryset = queryset.filter(talk_time__lte=talk_time_max)

        ordering = self.request.query_params.get("ordering", "-received_at")
        allowed_ordering = {
            "received_at",
            "call_date",
            "talk_time",
            "agent_user",
            "agent_name",
            "team_name",
            "campaign",
            "disposition",
        }
        if ordering.lstrip("-") not in allowed_ordering:
            raise ValidationError({"ordering": "Unsupported sort order."})
        return queryset.order_by(ordering, "-id")


class CallFilterOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = scoped_calls(request.user)

        def choices(field):
            return list(
                queryset.exclude(**{field: ""})
                .order_by(field)
                .values_list(field, flat=True)
                .distinct()[:250]
            )

        def case_insensitive_choices(values):
            unique = {}
            for value in values:
                unique.setdefault(value.casefold(), value)
            return sorted(unique.values(), key=str.casefold)[:250]

        return Response(
            {
                "agents": sorted(
                    set(choices("agent_name"))
                    | set(
                        queryset.filter(agent_name="")
                        .exclude(agent_user="")
                        .values_list("agent_user", flat=True)[:250]
                    ),
                    key=str.casefold,
                )[:250],
                "teams": case_insensitive_choices(
                    list(
                        queryset.filter(team__isnull=False)
                        .order_by("team__name")
                        .values_list("team__name", flat=True)
                        .distinct()[:250]
                    )
                    + list(
                        queryset.filter(team__isnull=True)
                        .exclude(team_name="")
                        .order_by("team_name")
                        .values_list("team_name", flat=True)
                        .distinct()[:250]
                    )
                ),
                "campaigns": choices("campaign"),
                "dispositions": choices("disposition"),
                "dialers": choices("dialer__name"),
                "event_types": [
                    {"value": value, "label": label}
                    for value, label in CallEvent.EventType.choices
                ],
                "recording_statuses": [
                    {"value": value, "label": label}
                    for value, label in CallEvent.Status.choices
                ],
            }
        )


class RecordingView(ListAPIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _file_chunks(path, start, length, chunk_size=64 * 1024):
        with path.open("rb") as recording:
            recording.seek(start)
            remaining = length
            while remaining > 0:
                chunk = recording.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    @staticmethod
    def _range_bounds(value, file_size):
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
        if not match or file_size <= 0:
            return None
        start_text, end_text = match.groups()
        if not start_text and not end_text:
            return None
        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            return max(file_size - suffix_length, 0), file_size - 1
        start = int(start_text)
        if start >= file_size:
            return None
        end = min(int(end_text), file_size - 1) if end_text else file_size - 1
        if end < start:
            return None
        return start, end

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
        as_attachment = request.query_params.get("download") == "1"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        file_size = path.stat().st_size
        range_header = request.headers.get("Range")

        if range_header:
            bounds = self._range_bounds(range_header, file_size)
            if bounds is None:
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{file_size}"
                response["Accept-Ranges"] = "bytes"
                return response
            start, end = bounds
            response = StreamingHttpResponse(
                self._file_chunks(path, start, end - start + 1),
                status=206,
                content_type=content_type,
            )
            response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            response["Content-Length"] = str(end - start + 1)
        else:
            response = FileResponse(
                path.open("rb"),
                as_attachment=as_attachment,
                filename=path.name,
                content_type=content_type,
            )
            response["Content-Length"] = str(file_size)

        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = content_disposition_header(
            as_attachment, path.name
        )
        return response
