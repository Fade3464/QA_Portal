import json
import logging
import mimetypes
import re
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.db.models import (
    Avg,
    Count,
    Exists,
    FloatField,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, TruncDate
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
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

from .models import CallEvent, Review, ReviewWorkflowEvent
from .scorecard import SCORECARD, SCORECARD_VERSION, calculate_score, rating_for, scorecard_payload
from .serializers import (
    CallEventSerializer,
    ReviewDetailSerializer,
    ReviewListSerializer,
    ReviewSerializer,
)
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
    if user.role not in {User.Role.QA, User.Role.TEAM_LEADER}:
        return queryset
    if user.role == User.Role.TEAM_LEADER:
        # Team Leaders may share a branch and project, so branch/project scope
        # alone is not sufficient. Keep unassigned calls and calls belonging to
        # another leader out of every call-library-backed endpoint.
        queryset = queryset.filter(team__team_leader_id=user.pk)
    allowed_project = QAProjectAssignment.objects.filter(
        qa=user,
        dialer_campaign__dialer_id=OuterRef("dialer_id"),
        dialer_campaign__campaign__iexact=OuterRef("campaign"),
    )
    return queryset.annotate(_project_allowed=Exists(allowed_project)).filter(
        _project_allowed=True
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
        if review.status in {
            Review.Status.COMPLETED,
            Review.Status.DISPUTED,
            Review.Status.REVISION_REQUIRED,
        }:
            raise ReservationConflict(
                "A submitted or returned review cannot be released."
            )
        review.delete()
        transaction.on_commit(lambda: _broadcast_reservation(call, None))
        return Response(status=204)


class CallReviewDraftView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def patch(self, request, pk):
        _call, review = _owned_review(request.user, pk, for_update=True)
        if review.status not in {
            Review.Status.IN_PROGRESS,
            Review.Status.REVISION_REQUIRED,
        }:
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
        is_resubmission = review.status == Review.Status.REVISION_REQUIRED
        serializer = ReviewSerializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        merged = {
            field: serializer.validated_data.get(field, getattr(review, field))
            for field in (
                "scores",
                "criterion_evidence",
                "critical_errors",
                "critical_error_evidence",
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
        critical_errors = list(dict.fromkeys(merged["critical_errors"]))
        unselected_evidence = set(merged["critical_error_evidence"]) - set(
            critical_errors
        )
        if unselected_evidence:
            raise ValidationError(
                {
                    "critical_error_evidence": (
                        "Evidence can only be attached to selected critical errors."
                    )
                }
            )
        if critical_errors:
            # Critical errors determine the outcome independently. Validate any
            # optional scoring that was entered, but only persist a comparable
            # numeric score when the complete scorecard is present.
            calculate_score(merged["scores"], require_complete=False)
            try:
                score = calculate_score(merged["scores"], require_complete=True)
            except ValidationError:
                score = None
        else:
            score = calculate_score(merged["scores"], require_complete=True)
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
        if is_resubmission:
            review.leader_status = Review.LeaderStatus.PENDING
            review.leader_reviewed_at = None
            review.leader_closed_at = None
            review.leader_updated_at = now
            review.coaching_due_at = None
            review.revision_requested_at = None
            review.revision_reason = ""
        review.save()

        from apps.notifications.services import (
            queue_review_report_notification,
            resolve_review_returned_notifications,
        )

        if is_resubmission:
            ReviewWorkflowEvent.objects.create(
                review=review,
                actor=request.user,
                event_type=ReviewWorkflowEvent.EventType.STATUS_CHANGED,
                from_status=Review.LeaderStatus.RETURNED_TO_QA,
                to_status=Review.LeaderStatus.PENDING,
                note="Reassessed and resubmitted to the Team Leader.",
            )
            resolve_review_returned_notifications(review)
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


def _report_base_queryset():
    project = DialerCampaign.objects.filter(
        dialer_id=OuterRef("call__dialer_id"),
        campaign__iexact=OuterRef("call__campaign"),
    ).values("project_name")[:1]
    queryset = Review.objects.select_related(
        "call",
        "call__dialer",
        "call__branch",
        "call__team",
        "reviewer",
        "team_leader",
    ).annotate(project_name=Subquery(project))
    return queryset


def _report_queryset(user):
    queryset = _report_base_queryset()
    if user.is_superuser:
        return queryset
    if user.role == User.Role.QA:
        return queryset.filter(reviewer=user)
    completed = (Review.Status.COMPLETED, Review.Status.DISPUTED)
    if user.role == User.Role.TEAM_LEADER:
        allowed_project = QAProjectAssignment.objects.filter(
            qa=user,
            dialer_campaign__dialer_id=OuterRef("call__dialer_id"),
            dialer_campaign__campaign__iexact=OuterRef("call__campaign"),
        )
        return (
            queryset.filter(team_leader=user, status__in=completed)
            .annotate(_project_allowed=Exists(allowed_project))
            .filter(_project_allowed=True)
        )
    return queryset.filter(call__branch_id=user.branch_id, status__in=completed)


def _report_param_list(params, name, *, maximum=50):
    values = params.getlist(name) if hasattr(params, "getlist") else []
    if not values and params.get(name):
        values = [params.get(name)]
    normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    if len(normalized) > maximum:
        raise ValidationError({name: f"Select at most {maximum} values."})
    return normalized


def _score_rule_catalog():
    categories = {category["key"]: category for category in SCORECARD}
    criteria = {
        key: {"key": key, "label": label, "max_score": maximum, "category": category["key"]}
        for category in SCORECARD
        for key, label, maximum in category["criteria"]
    }
    return categories, criteria


def _parse_score_rules(raw):
    if not raw:
        return []
    if len(raw) > 12000:
        raise ValidationError({"score_rules": "The score query is too large."})
    try:
        rules = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"score_rules": "Enter a valid score query."}) from exc
    if not isinstance(rules, list) or len(rules) > 12:
        raise ValidationError({"score_rules": "Use a list containing at most 12 rules."})

    categories, criteria = _score_rule_catalog()
    allowed_operators = {"gt", "gte", "lt", "lte", "eq", "neq", "between", "outside"}
    normalized = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValidationError({"score_rules": f"Rule {index + 1} is invalid."})
        scope = rule.get("scope")
        key = rule.get("key")
        operator = rule.get("operator")
        unit = rule.get("unit", "points")
        if scope == "total":
            key, maximum = "total", 100
        elif scope == "category" and key in categories:
            maximum = categories[key]["max_score"]
        elif scope == "criterion" and key in criteria:
            maximum = criteria[key]["max_score"]
        else:
            raise ValidationError({"score_rules": f"Rule {index + 1} has an unknown score field."})
        if operator not in allowed_operators:
            raise ValidationError({"score_rules": f"Rule {index + 1} has an unsupported operator."})
        if unit not in {"points", "percent"}:
            raise ValidationError({"score_rules": f"Rule {index + 1} has an unsupported unit."})
        try:
            value = float(rule["value"])
            value_to = float(rule["value_to"]) if operator in {"between", "outside"} else None
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError({"score_rules": f"Rule {index + 1} needs numeric values."}) from exc
        ceiling = 100 if unit == "percent" else maximum
        if not 0 <= value <= ceiling or (value_to is not None and not 0 <= value_to <= ceiling):
            raise ValidationError({"score_rules": f"Rule {index + 1} must be between 0 and {ceiling}."})
        if unit == "percent":
            value = value * maximum / 100
            value_to = value_to * maximum / 100 if value_to is not None else None
        if value_to is not None and value > value_to:
            value, value_to = value_to, value
        normalized.append({"scope": scope, "key": key, "operator": operator, "value": value, "value_to": value_to})
    return normalized


def _score_rule_expression(rule):
    if rule["scope"] == "total":
        return "score", Q(score__isnull=False)
    categories, criteria = _score_rule_catalog()
    if rule["scope"] == "criterion":
        keys = [rule["key"]]
    else:
        keys = [key for key, _label, _maximum in categories[rule["key"]]["criteria"]]
    expression = Value(0.0, output_field=FloatField())
    for key in keys:
        expression += Coalesce(Cast(KeyTextTransform(key, "scores"), FloatField()), Value(0.0))
    return expression, Q(scores__has_keys=keys)


def _score_rule_condition(alias, rule):
    operator = rule["operator"]
    value = rule["value"]
    if operator in {"gt", "gte", "lt", "lte"}:
        return Q(**{f"{alias}__{operator}": value})
    if operator == "eq":
        return Q(**{alias: value})
    if operator == "neq":
        return ~Q(**{alias: value})
    bounds = Q(**{f"{alias}__gte": value, f"{alias}__lte": rule["value_to"]})
    return bounds if operator == "between" else ~bounds


def _apply_score_rules(queryset, params):
    rules = _parse_score_rules(params.get("score_rules", ""))
    if not rules:
        return queryset
    match = params.get("score_match", "all")
    if match not in {"all", "any"}:
        raise ValidationError({"score_match": "Use all or any."})
    annotations = {}
    conditions = []
    for index, rule in enumerate(rules):
        alias = f"_score_rule_{index}"
        expression, present = _score_rule_expression(rule)
        if rule["scope"] != "total":
            annotations[alias] = expression
        else:
            alias = "score"
        conditions.append(present & _score_rule_condition(alias, rule))
    if annotations:
        queryset = queryset.annotate(**annotations)
    if match == "all":
        for condition in conditions:
            queryset = queryset.filter(condition)
        return queryset
    combined = Q()
    for condition in conditions:
        combined |= condition
    return queryset.filter(combined)


def _report_filters(queryset, params):
    search = params.get("search", "").strip()
    if len(search) > 160:
        raise ValidationError({"search": "Search must be 160 characters or fewer."})
    if search:
        queryset = queryset.filter(
            Q(call__agent_name__icontains=search)
            | Q(call__agent_user__icontains=search)
            | Q(call__phone_number__icontains=search)
            | Q(call__team__name__icontains=search)
            | Q(reviewer__first_name__icontains=search)
            | Q(reviewer__last_name__icontains=search)
        )

    workflow_statuses = _report_param_list(params, "workflow_status")
    if workflow_statuses:
        valid = {choice for choice, _label in Review.LeaderStatus.choices}
        if not set(workflow_statuses) <= valid:
            raise ValidationError({"workflow_status": "Unsupported workflow status."})
        queryset = queryset.filter(leader_status__in=workflow_statuses)

    ratings = _report_param_list(params, "rating")
    if ratings:
        valid = {choice for choice, _label in Review.Rating.choices}
        if not set(ratings) <= valid:
            raise ValidationError({"rating": "Unsupported rating."})
        queryset = queryset.filter(rating__in=ratings)

    segment = params.get("segment", "all").strip()
    if segment == "attention":
        queryset = queryset.filter(leader_status=Review.LeaderStatus.PENDING)
    elif segment == "critical":
        queryset = queryset.exclude(critical_errors=[]).exclude(
            leader_status=Review.LeaderStatus.CLOSED
        )
    elif segment == "coaching":
        queryset = queryset.filter(leader_status=Review.LeaderStatus.COACHING_PLANNED)
    elif segment == "closed":
        queryset = queryset.filter(leader_status=Review.LeaderStatus.CLOSED)
    elif segment != "all":
        raise ValidationError({"segment": "Unsupported report segment."})

    for name, lookup in (
        ("project", "project_name__in"),
        ("reviewer", "reviewer_id__in"),
        ("team", "call__team__name__in"),
        ("agent", "call__agent_name__in"),
        ("disposition", "call__disposition__in"),
        ("direction", "call__call_direction__in"),
    ):
        values = _report_param_list(params, name)
        if values:
            if name == "reviewer":
                try:
                    [UUID(value) for value in values]
                except ValueError as exc:
                    raise ValidationError({"reviewer": "Select valid QA analysts."}) from exc
            valid_directions = {choice for choice, _label in CallEvent.Direction.choices}
            if name == "direction" and not set(values) <= valid_directions:
                raise ValidationError({"direction": "Unsupported call direction."})
            queryset = queryset.filter(**{lookup: values})

    critical = params.get("critical", "").strip().lower()
    if critical == "true":
        queryset = queryset.exclude(critical_errors=[])
    elif critical == "false":
        queryset = queryset.filter(critical_errors=[])
    elif critical:
        raise ValidationError({"critical": "Use true or false."})

    score_state = params.get("score_state", "all").strip()
    if score_state == "scored":
        queryset = queryset.filter(score__isnull=False)
    elif score_state == "unscored":
        queryset = queryset.filter(score__isnull=True)
    elif score_state != "all":
        raise ValidationError({"score_state": "Use all, scored, or unscored."})

    date_from = parse_date(params.get("date_from", ""))
    date_to = parse_date(params.get("date_to", ""))
    if params.get("date_from") and not date_from:
        raise ValidationError({"date_from": "Enter a valid date."})
    if params.get("date_to") and not date_to:
        raise ValidationError({"date_to": "Enter a valid date."})
    if date_from and date_to and date_from > date_to:
        raise ValidationError({"date_to": "The end date must be on or after the start date."})
    date_field = params.get("date_field", "completed_at")
    if date_field not in {"completed_at", "call_date"}:
        raise ValidationError({"date_field": "Use completed_at or call_date."})
    date_lookup = "completed_at__date" if date_field == "completed_at" else "call__call_date__date"
    if date_from:
        queryset = queryset.filter(**{f"{date_lookup}__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{date_lookup}__lte": date_to})

    queryset = _apply_score_rules(queryset, params)

    ordering = params.get("ordering", "-completed_at")
    allowed_ordering = {
        "-completed_at",
        "completed_at",
        "score",
        "-score",
        "coaching_due_at",
        "-leader_updated_at",
    }
    if ordering not in allowed_ordering:
        raise ValidationError({"ordering": "Unsupported report ordering."})
    return queryset.order_by(ordering, "-assigned_at")


class ReviewReportListView(ListAPIView):
    serializer_class = ReviewListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ReviewPagination

    def get_queryset(self):
        return _report_filters(
            _report_queryset(self.request.user), self.request.query_params
        )


class ReviewReportSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = _report_queryset(request.user).filter(
            status__in=(Review.Status.COMPLETED, Review.Status.DISPUTED)
        )
        now = timezone.now()
        open_queryset = queryset.exclude(leader_status=Review.LeaderStatus.CLOSED)
        totals = queryset.aggregate(total=Count("id"), average_score=Avg("score"))
        start_date = timezone.localdate() - timedelta(days=13)
        raw_trend = {
            item["day"]: item
            for item in queryset.filter(completed_at__date__gte=start_date)
            .annotate(day=TruncDate("completed_at"))
            .values("day")
            .annotate(count=Count("id"), average_score=Avg("score"))
            .order_by("day")
        }
        trend = []
        for offset in range(14):
            day = start_date + timedelta(days=offset)
            item = raw_trend.get(day, {})
            trend.append(
                {
                    "date": day.isoformat(),
                    "count": item.get("count", 0),
                    "average_score": round(float(item["average_score"]), 2)
                    if item.get("average_score") is not None
                    else None,
                }
            )
        return Response(
            {
                "total": totals["total"],
                "average_score": round(float(totals["average_score"]), 2)
                if totals["average_score"] is not None
                else None,
                "pending": queryset.filter(
                    leader_status=Review.LeaderStatus.PENDING
                ).count(),
                "critical_open": open_queryset.exclude(critical_errors=[]).count(),
                "coaching_open": queryset.filter(
                    leader_status=Review.LeaderStatus.COACHING_PLANNED
                ).count(),
                "overdue": queryset.filter(
                    leader_status=Review.LeaderStatus.COACHING_PLANNED,
                    coaching_due_at__lt=now,
                ).count(),
                "below_benchmark_open": open_queryset.filter(score__lt=85).count(),
                "closed": queryset.filter(
                    leader_status=Review.LeaderStatus.CLOSED
                ).count(),
                "trend": trend,
                "filters": {
                    "projects": list(
                        queryset.exclude(project_name__isnull=True)
                        .exclude(project_name="")
                        .order_by("project_name")
                        .values_list("project_name", flat=True)
                        .distinct()
                    ),
                    "reviewers": list(
                        queryset.order_by("reviewer__first_name", "reviewer__last_name")
                        .values(
                            "reviewer_id", "reviewer__first_name", "reviewer__last_name"
                        )
                        .distinct()
                    ),
                    "teams": list(
                        queryset.exclude(call__team__name="")
                        .order_by("call__team__name")
                        .values_list("call__team__name", flat=True)
                        .distinct()
                    ),
                    "agents": list(
                        queryset.exclude(call__agent_name="")
                        .order_by("call__agent_name")
                        .values_list("call__agent_name", flat=True)
                        .distinct()
                    ),
                    "dispositions": list(
                        queryset.exclude(call__disposition="")
                        .order_by("call__disposition")
                        .values_list("call__disposition", flat=True)
                        .distinct()
                    ),
                    "directions": list(
                        queryset.exclude(call__call_direction="")
                        .order_by("call__call_direction")
                        .values_list("call__call_direction", flat=True)
                        .distinct()
                    ),
                    "scorecard": scorecard_payload(),
                },
                "generated_at": now,
            }
        )


class ReviewReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        review = (
            _report_queryset(request.user)
            .prefetch_related("workflow_events__actor")
            .filter(pk=pk)
            .first()
        )
        if not review:
            raise NotFound("QA report not found.")
        return Response(
            ReviewDetailSerializer(review, context={"request": request}).data
        )


class ReviewReportActionView(APIView):
    permission_classes = [IsAuthenticated]

    transitions = {
        Review.LeaderStatus.PENDING: {
            Review.LeaderStatus.ACKNOWLEDGED,
            Review.LeaderStatus.COACHING_PLANNED,
            Review.LeaderStatus.ESCALATED,
            Review.LeaderStatus.RETURNED_TO_QA,
        },
        Review.LeaderStatus.ACKNOWLEDGED: {
            Review.LeaderStatus.COACHING_PLANNED,
            Review.LeaderStatus.ESCALATED,
            Review.LeaderStatus.CLOSED,
            Review.LeaderStatus.RETURNED_TO_QA,
        },
        Review.LeaderStatus.COACHING_PLANNED: {
            Review.LeaderStatus.COACHING_COMPLETED,
            Review.LeaderStatus.ESCALATED,
            Review.LeaderStatus.RETURNED_TO_QA,
        },
        Review.LeaderStatus.COACHING_COMPLETED: {
            Review.LeaderStatus.COACHING_PLANNED,
            Review.LeaderStatus.CLOSED,
            Review.LeaderStatus.RETURNED_TO_QA,
        },
        Review.LeaderStatus.ESCALATED: {
            Review.LeaderStatus.COACHING_PLANNED,
            Review.LeaderStatus.CLOSED,
            Review.LeaderStatus.RETURNED_TO_QA,
        },
        Review.LeaderStatus.CLOSED: {
            Review.LeaderStatus.ACKNOWLEDGED,
            Review.LeaderStatus.RETURNED_TO_QA,
        },
        Review.LeaderStatus.RETURNED_TO_QA: set(),
    }

    @transaction.atomic
    def post(self, request, pk):
        if request.user.role != User.Role.TEAM_LEADER and not request.user.is_superuser:
            raise PermissionDenied(
                "Only the assigned Team Leader can manage this report."
            )
        review = (
            _report_queryset(request.user)
            .select_for_update(of=("self",))
            .filter(pk=pk)
            .first()
        )
        if not review:
            raise NotFound("QA report not found.")

        note = str(request.data.get("note", "")).strip()
        if len(note) > 4000:
            raise ValidationError({"note": "Keep notes within 4,000 characters."})
        target = str(request.data.get("leader_status", "")).strip()
        if not target:
            if not note:
                raise ValidationError({"note": "Enter a note to add to the report."})
            target = review.leader_status
        valid_statuses = {choice for choice, _label in Review.LeaderStatus.choices}
        if target not in valid_statuses:
            raise ValidationError({"leader_status": "Unsupported workflow status."})
        status_changed = target != review.leader_status
        if status_changed and target not in self.transitions[review.leader_status]:
            raise ValidationError(
                {"leader_status": "That workflow transition is not available."}
            )
        if (
            target
            in {
                Review.LeaderStatus.COACHING_PLANNED,
                Review.LeaderStatus.COACHING_COMPLETED,
                Review.LeaderStatus.ESCALATED,
                Review.LeaderStatus.RETURNED_TO_QA,
            }
            and not note
        ):
            raise ValidationError({"note": "Document the reason for this action."})

        due_at = None
        raw_due_at = request.data.get("coaching_due_at")
        if raw_due_at:
            due_at = parse_datetime(str(raw_due_at))
            if due_at is None:
                raise ValidationError(
                    {"coaching_due_at": "Enter a valid date and time."}
                )
            if timezone.is_naive(due_at):
                due_at = timezone.make_aware(due_at)
        if target == Review.LeaderStatus.COACHING_PLANNED:
            if due_at is None:
                raise ValidationError(
                    {"coaching_due_at": "Choose when coaching should be completed."}
                )
            if due_at <= timezone.now():
                raise ValidationError(
                    {"coaching_due_at": "The coaching deadline must be in the future."}
                )

        previous = review.leader_status
        now = timezone.now()
        if review.leader_reviewed_at is None:
            review.leader_reviewed_at = now
        if status_changed:
            review.leader_status = target
            review.leader_closed_at = (
                now if target == Review.LeaderStatus.CLOSED else None
            )
            if target == Review.LeaderStatus.COACHING_PLANNED:
                review.coaching_due_at = due_at
            elif target == Review.LeaderStatus.RETURNED_TO_QA:
                review.status = Review.Status.REVISION_REQUIRED
                review.coaching_due_at = None
                review.revision_requested_at = now
                review.revision_reason = note
                review.revision_count += 1
        review.leader_updated_at = now
        review.save(
            update_fields=[
                "leader_status",
                "coaching_due_at",
                "leader_reviewed_at",
                "leader_closed_at",
                "leader_updated_at",
                "status",
                "revision_requested_at",
                "revision_reason",
                "revision_count",
            ]
        )
        workflow_event = ReviewWorkflowEvent.objects.create(
            review=review,
            actor=request.user,
            event_type=(
                ReviewWorkflowEvent.EventType.STATUS_CHANGED
                if status_changed
                else ReviewWorkflowEvent.EventType.NOTE_ADDED
            ),
            from_status=previous,
            to_status=target,
            note=note,
            coaching_due_at=review.coaching_due_at,
            email_status=(
                Review.EmailStatus.PENDING
                if target == Review.LeaderStatus.RETURNED_TO_QA
                and settings.QA_RETURN_EMAIL_ENABLED
                else Review.EmailStatus.DISABLED
            ),
        )
        from apps.notifications.services import (
            queue_review_returned_notification,
            resolve_review_report_notification,
        )

        resolve_review_report_notification(review, request.user)
        if target == Review.LeaderStatus.RETURNED_TO_QA:
            queue_review_returned_notification(review, workflow_event)
            if settings.QA_RETURN_EMAIL_ENABLED:
                from apps.notifications.tasks import send_review_returned_email

                transaction.on_commit(
                    lambda: send_review_returned_email.delay(str(workflow_event.pk))
                )
        review = (
            _report_base_queryset()
            .prefetch_related("workflow_events__actor")
            .get(pk=review.pk)
        )
        return Response(
            ReviewDetailSerializer(review, context={"request": request}).data
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
