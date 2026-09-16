import logging
import mimetypes
import re
from pathlib import Path

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import content_disposition_header
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CallEvent, Review
from .scorecard import SCORECARD_VERSION, calculate_score, rating_for, scorecard_payload
from .serializers import CallEventSerializer, ReviewListSerializer, ReviewSerializer
from apps.accounts.models import User
from apps.tenancy.models import DialerCampaign, QAProjectAssignment

logger = logging.getLogger(__name__)


def scoped_calls(user):
    project = DialerCampaign.objects.filter(
        dialer_id=OuterRef("dialer_id"),
        campaign__iexact=OuterRef("campaign"),
    ).values("project_name")[:1]
    queryset = CallEvent.objects.select_related(
        "dialer", "branch", "team", "review__reviewer"
    ).annotate(project_name=Subquery(project))
    if user.is_superuser:
        return queryset
    queryset = queryset.filter(branch_id=user.branch_id)
    if user.role != User.Role.QA:
        return queryset
    allowed_project = QAProjectAssignment.objects.filter(
        qa=user,
        dialer_campaign__dialer_id=OuterRef("dialer_id"),
        dialer_campaign__campaign__iexact=OuterRef("campaign"),
    )
    return queryset.annotate(_qa_project_allowed=Exists(allowed_project)).filter(
        _qa_project_allowed=True
    )


class CallPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ReservationConflict(APIException):
    status_code = 409
    default_code = "reservation_conflict"
    default_detail = "This call is already reserved by another QA analyst."


def _analysis_call(user, pk, *, for_update=False):
    if user.role != User.Role.QA or user.is_superuser:
        raise PermissionDenied("Only QA analysts can analyze calls.")
    queryset = scoped_calls(user)
    if for_update:
        # Lock only the call row. The scoped queryset includes an optional
        # review via an outer join, which PostgreSQL cannot lock directly.
        queryset = queryset.select_for_update(of=("self",))
    call = queryset.filter(pk=pk).first()
    if not call:
        raise NotFound("Call not found.")
    if (
        call.recording_download_status != CallEvent.Status.DOWNLOADED
        or not call.recording_path
    ):
        raise ReservationConflict("The recording is not ready for analysis yet.")
    return call


def _reservation_data(review, user=None):
    if not review:
        return None
    return {
        "review_id": str(review.pk),
        "reviewer_id": str(review.reviewer_id),
        "reviewer_name": review.reviewer.full_name,
        "status": review.status,
        "reserved_at": review.assigned_at.isoformat(),
        "is_mine": bool(user and user.pk == review.reviewer_id),
    }


def _owned_review(user, pk, *, for_update=False):
    call = _analysis_call(user, pk, for_update=for_update)
    queryset = Review.objects.select_related("reviewer")
    if for_update:
        queryset = queryset.select_for_update()
    review = queryset.filter(call=call).first()
    if not review:
        raise ReservationConflict("Reserve this call before entering QA findings.")
    if review.reviewer_id != user.pk:
        raise ReservationConflict(
            f"This call is reserved by {review.reviewer.full_name}."
        )
    return call, review


def _broadcast_reservation(call, review):
    payload = {
        "type": "call.reservation",
        "call_id": str(call.pk),
        "reservation": _reservation_data(review),
    }
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"analysis_{call.pk}", {"type": "analysis.event", "payload": payload}
        )
        qa_ids = call.dialer.campaigns.filter(
            campaign__iexact=call.campaign,
            qa_assignments__qa__is_active=True,
        ).values_list("qa_assignments__qa_id", flat=True)
        for qa_id in qa_ids:
            async_to_sync(channel_layer.group_send)(
                f"user_{qa_id}",
                {"type": "portal.notification", "payload": payload},
            )
    except Exception:
        # The database is authoritative; a temporary Redis outage must not
        # turn a successfully committed reservation into an apparent failure.
        logger.exception("Unable to broadcast call reservation update")


class CallAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        call = _analysis_call(request.user, pk)
        try:
            review = call.review
        except Review.DoesNotExist:
            review = None
        return Response(
            {
                "call": CallEventSerializer(call, context={"request": request}).data,
                "review": ReviewSerializer(review).data if review else None,
                "scorecard": scorecard_payload(),
            }
        )


class CallReserveView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        call = _analysis_call(request.user, pk, for_update=True)
        review = Review.objects.select_related("reviewer").filter(call=call).first()
        if review and review.reviewer_id != request.user.pk:
            raise ReservationConflict(
                f"This call is reserved by {review.reviewer.full_name}."
            )
        if not review:
            review = Review.objects.create(
                call=call,
                reviewer=request.user,
                status=Review.Status.IN_PROGRESS,
            )
            review = Review.objects.select_related("reviewer").get(pk=review.pk)
            transaction.on_commit(lambda: _broadcast_reservation(call, review))
        return Response(_reservation_data(review, request.user))


class CallReleaseView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        call = _analysis_call(request.user, pk, for_update=True)
        review = Review.objects.select_related("reviewer").filter(call=call).first()
        if not review:
            return Response(status=204)
        if review.reviewer_id != request.user.pk:
            raise PermissionDenied(
                "Only the QA analyst who reserved this call can release it."
            )
        if review.status in {Review.Status.COMPLETED, Review.Status.DISPUTED}:
            raise ReservationConflict(
                "A completed or disputed review cannot be released."
            )
        review.delete()
        transaction.on_commit(lambda: _broadcast_reservation(call, None))
        return Response(status=204)


class CallReviewDraftView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, pk):
        _call, review = _owned_review(request.user, pk, for_update=True)
        if review.status != Review.Status.IN_PROGRESS:
            raise ReservationConflict("A submitted report cannot be changed.")
        serializer = ReviewSerializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            score=calculate_score(
                serializer.validated_data.get("scores", review.scores),
                require_complete=False,
            ),
            scorecard_version=SCORECARD_VERSION,
            scorecard_snapshot=scorecard_payload(),
        )
        return Response(ReviewSerializer(review).data)


class CallReviewSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        call, review = _owned_review(request.user, pk, for_update=True)
        if review.status == Review.Status.COMPLETED:
            return Response(ReviewSerializer(review).data)
        serializer = ReviewSerializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        merged = {
            field: serializer.validated_data.get(field, getattr(review, field))
            for field in (
                "scores",
                "criterion_evidence",
                "critical_errors",
                "feedback_summary",
                "strengths",
                "expected_behavior",
                "coaching_plan",
            )
        }
        if not call.team_id:
            raise ValidationError(
                {"team": "Assign this call to a team before submitting its report."}
            )
        team_leader = call.team.team_leader
        if not team_leader.is_active:
            raise ValidationError(
                {"team_leader": "The assigned Team Leader account is inactive."}
            )
        score = calculate_score(merged["scores"], require_complete=True)
        critical_errors = list(dict.fromkeys(merged["critical_errors"]))
        rating, outcome = rating_for(score, bool(critical_errors))
        now = timezone.now()
        email_status = (
            Review.EmailStatus.PENDING
            if settings.QA_REPORT_EMAIL_ENABLED
            else Review.EmailStatus.DISABLED
        )
        for field, value in merged.items():
            setattr(review, field, value)
        review.critical_errors = critical_errors
        review.score = score
        review.rating = rating
        review.outcome = outcome
        review.scorecard_version = SCORECARD_VERSION
        review.scorecard_snapshot = scorecard_payload()
        review.team_leader = team_leader
        review.status = Review.Status.COMPLETED
        review.completed_at = now
        review.email_status = email_status
        review.email_last_error = ""
        review.save()

        from apps.notifications.services import queue_review_report_notification

        notification = queue_review_report_notification(review)
        transaction.on_commit(lambda: _broadcast_reservation(call, review))
        if settings.QA_REPORT_EMAIL_ENABLED:
            from apps.notifications.tasks import send_review_report_email

            transaction.on_commit(
                lambda: send_review_report_email.delay(str(review.pk))
            )
        response = ReviewSerializer(review).data
        response["notification_id"] = str(notification.pk)
        return Response(response)


class ReviewPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ReviewReportListView(ListAPIView):
    serializer_class = ReviewListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ReviewPagination

    def get_queryset(self):
        project = DialerCampaign.objects.filter(
            dialer_id=OuterRef("call__dialer_id"),
            campaign__iexact=OuterRef("call__campaign"),
        ).values("project_name")[:1]
        queryset = Review.objects.select_related(
            "call",
            "call__team",
            "reviewer",
            "team_leader",
        ).annotate(project_name=Subquery(project))
        user = self.request.user
        if user.is_superuser:
            return queryset
        if user.role == User.Role.QA:
            return queryset.filter(reviewer=user)
        if user.role == User.Role.TEAM_LEADER:
            return queryset.filter(team_leader=user, status=Review.Status.COMPLETED)
        return queryset.filter(
            call__branch_id=user.branch_id, status=Review.Status.COMPLETED
        )


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
                raise ValidationError(
                    {name: f"Unsupported value: {sorted(invalid)[0]}"}
                )
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
                | Q(project_name__icontains=search)
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

        if termination_reasons := self._values("termination_reason"):
            termination_query = Q()
            for value in termination_reasons:
                termination_query |= Q(termination_reason__iexact=value)
            queryset = queryset.filter(termination_query)

        if project_values := self._values("project"):
            project_query = Q()
            for value in project_values:
                project_query |= Q(project_name__iexact=value)
            queryset = queryset.filter(project_query)

        if event_types := self._values(
            "event_type", allowed=CallEvent.EventType.values
        ):
            queryset = queryset.filter(event_type__in=event_types)
        if dial_methods := self._values(
            "dial_method", allowed=CallEvent.DialMethod.values
        ):
            queryset = queryset.filter(dial_method__in=dial_methods)
        if recording_statuses := self._values(
            "recording_status", allowed=CallEvent.Status.values
        ):
            queryset = queryset.filter(recording_download_status__in=recording_statuses)

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
            "lead_id",
            "phone_number",
            "received_at",
            "call_date",
            "talk_time",
            "agent_user",
            "agent_name",
            "team_name",
            "campaign",
            "project_name",
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
                "projects": case_insensitive_choices(choices("project_name")),
                "dispositions": choices("disposition"),
                "termination_reasons": case_insensitive_choices(
                    choices("termination_reason")
                ),
                "dialers": choices("dialer__name"),
                "event_types": [
                    {"value": value, "label": label}
                    for value, label in CallEvent.EventType.choices
                ],
                "dial_methods": [
                    {"value": value, "label": label}
                    for value, label in CallEvent.DialMethod.choices
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
