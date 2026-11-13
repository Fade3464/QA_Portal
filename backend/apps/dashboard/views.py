from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.calls.models import CallEvent, Review
from apps.calls.serializers import CallEventSerializer
from apps.calls.views import scoped_calls
from apps.access.report_scope import scoped_reports
from apps.accounts.models import User
from apps.tenancy.access import branch_projects
from apps.tenancy.models import DialerCampaign, QAProjectAssignment

from .project_filters import parse_project_selections


def health(request):
    return JsonResponse({"status": "ok"})


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        calls = scoped_calls(request.user)
        since = timezone.now() - timedelta(hours=24)
        recent = calls.filter(effective_received_at__gte=since).order_by("-effective_received_at")
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


class ProjectPerformanceView(APIView):
    """Decision-focused QA performance for the projects visible to the user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return self._response(request, request.query_params)

    def post(self, request):
        # A body keeps large selections and long project names out of URL limits.
        if not isinstance(request.data, dict) or set(request.data) - {"days", "projects"}:
            raise ValidationError({"projects": "Send days and a list of dialer projects."})
        return self._response(request, request.data)

    def _response(self, request, filters):
        if not request.user.is_superuser and request.user.role not in {
            User.Role.PROJECT_MANAGER,
            User.Role.SUPERVISOR,
        }:
            raise PermissionDenied("Project performance is available to management users.")

        try:
            days = int(str(filters.get("days", "30")))
        except ValueError as exc:
            raise ValidationError({"days": "Choose today or a 7, 30, or 90 day window."}) from exc
        if days not in {1, 7, 30, 90}:
            raise ValidationError({"days": "Choose today or a 7, 30, or 90 day window."})

        if request.user.role == User.Role.PROJECT_MANAGER and not request.user.is_superuser:
            campaign_scope = DialerCampaign.objects.filter(
                pk__in=QAProjectAssignment.objects.filter(qa=request.user)
                .values("dialer_campaign_id"),
                dialer__branch_id=request.user.branch_id,
                dialer__branch__company_id=request.user.company_id,
            )
        else:
            campaign_scope = DialerCampaign.objects.all()
            if not request.user.is_superuser:
                campaign_scope = branch_projects(request.user)
        project_groups = {}
        for mapping in campaign_scope.order_by("dialer__name", "project_name").values(
            "dialer_id", "dialer__name", "project_name"
        ).distinct():
            dialer_id = str(mapping["dialer_id"])
            group = project_groups.setdefault(dialer_id, {
                "dialer_id": dialer_id,
                "dialer_name": mapping["dialer__name"],
                "projects": [],
            })
            group["projects"].append(mapping["project_name"])
        available_projects = sorted({
            name for group in project_groups.values() for name in group["projects"]
        })

        selections = parse_project_selections(filters, project_groups)
        project = filters.get("project", "").strip()
        if project and project not in available_projects:
            raise ValidationError({"project": "Choose a project assigned to you."})
        dialer_id = filters.get("dialer", "").strip()
        if dialer_id and (
            dialer_id not in project_groups
            or (project and project not in project_groups[dialer_id]["projects"])
        ):
            raise ValidationError({"dialer": "Choose an available dialer and project."})

        end_date = timezone.localdate()
        start_date = end_date - timedelta(days=days - 1)
        queryset = scoped_reports(request.user).filter(
            status__in=(Review.Status.COMPLETED, Review.Status.DISPUTED),
            completed_at__date__gte=start_date,
            completed_at__date__lte=end_date,
        )
        if project:
            queryset = queryset.filter(project_name=project)
        if dialer_id:
            queryset = queryset.filter(call__dialer_id=dialer_id)

        if selections:
            selected_scope = Q()
            for selection in selections:
                selected_scope |= Q(
                    project_name=selection["project"], call__dialer_id=selection["dialer"]
                )
            queryset = queryset.filter(selected_scope)

        totals = queryset.aggregate(
            evaluated=Count("id"),
            scored=Count("id", filter=Q(score__isnull=False)),
            average_score=Avg("score"),
            critical=Count("id", filter=~Q(critical_errors=[])),
            below_benchmark=Count("id", filter=Q(score__lt=85)),
        )
        evaluated = totals["evaluated"] or 0
        scored = totals["scored"] or 0

        raw_trend = {
            item["day"]: item
            for item in queryset.annotate(day=TruncDate("completed_at"))
            .values("day")
            .annotate(
                evaluated=Count("id"),
                average_score=Avg("score"),
                critical=Count("id", filter=~Q(critical_errors=[])),
            )
            .order_by("day")
        }
        trend = []
        for offset in range(days):
            day = start_date + timedelta(days=offset)
            item = raw_trend.get(day, {})
            trend.append(
                {
                    "date": day.isoformat(),
                    "evaluated": item.get("evaluated", 0),
                    "average_score": round(float(item["average_score"]), 2)
                    if item.get("average_score") is not None
                    else None,
                    "critical": item.get("critical", 0),
                }
            )

        teams = []
        team_rows = (
            queryset.values(
                "call__team_id",
                "call__team__name",
                "call__team__avatar",
                "call__team__team_leader__first_name",
                "call__team__team_leader__last_name",
            )
            .annotate(
                evaluated=Count("id"),
                scored=Count("id", filter=Q(score__isnull=False)),
                average_score=Avg("score"),
                critical=Count("id", filter=~Q(critical_errors=[])),
                below_benchmark=Count("id", filter=Q(score__lt=85)),
            )
            .order_by("call__team__name")
        )
        for row in team_rows:
            team_evaluated = row["evaluated"] or 0
            teams.append(
                {
                    "id": str(row["call__team_id"] or "unassigned"),
                    "name": row["call__team__name"] or "Unassigned team",
                    "avatar": row["call__team__avatar"] or "groups",
                    "team_leader": " ".join(
                        filter(
                            None,
                            (
                                row["call__team__team_leader__first_name"],
                                row["call__team__team_leader__last_name"],
                            ),
                        )
                    )
                    or "Unassigned",
                    "evaluated": team_evaluated,
                    "scored": row["scored"] or 0,
                    "average_score": round(float(row["average_score"]), 2)
                    if row["average_score"] is not None
                    else None,
                    "critical": row["critical"] or 0,
                    "critical_rate": round(
                        (row["critical"] or 0) / team_evaluated * 100, 1
                    )
                    if team_evaluated
                    else 0,
                    "below_benchmark": row["below_benchmark"] or 0,
                }
            )

        return Response(
            {
                "window": {"days": days, "from": start_date, "to": end_date},
                "selected_projects": selections or [],
                "selected_project": project or None,
                "selected_dialer": dialer_id or None,
                "projects": available_projects,
                "project_groups": list(project_groups.values()),
                "metrics": {
                    "evaluated": evaluated,
                    "scored": scored,
                    "average_score": round(float(totals["average_score"]), 2)
                    if totals["average_score"] is not None
                    else None,
                    "critical": totals["critical"] or 0,
                    "critical_rate": round((totals["critical"] or 0) / evaluated * 100, 1)
                    if evaluated
                    else 0,
                    "below_benchmark": totals["below_benchmark"] or 0,
                    "below_benchmark_rate": round(
                        (totals["below_benchmark"] or 0) / scored * 100, 1
                    )
                    if scored
                    else 0,
                },
                "trend": trend,
                "teams": teams,
                "generated_at": timezone.now(),
            }
        )


DIALER_OBSERVABILITY_WINDOWS = {
    "today": "Today",
    "6h": "6 hrs",
    "12h": "12 hrs",
    "yesterday": "Yesterday",
    "7d": "7 days",
    "month": "This month",
}


def _observability_window(key, tz):
    from datetime import datetime, time

    now_local = timezone.now().astimezone(tz)
    today = now_local.date()
    midnight = datetime.combine(today, time.min, tzinfo=tz)

    if key == "today":
        return midnight, now_local
    if key == "6h":
        return now_local - timedelta(hours=6), now_local
    if key == "12h":
        return now_local - timedelta(hours=12), now_local
    if key == "yesterday":
        return midnight - timedelta(days=1), midnight
    if key == "7d":
        return midnight - timedelta(days=6), now_local
    if key == "month":
        return midnight.replace(day=1), now_local
    raise ValidationError(
        {"window": "Choose Today, 6 hrs, 12 hrs, Yesterday, 7 days, or This month."}
    )


class DialerManagerObservabilityView(APIView):
    """Company-wide closer SALE/list observability for Dialer Managers only."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from zoneinfo import ZoneInfo
        from django.db.models.functions import Coalesce, Trim

        user = request.user
        if user.is_superuser or user.role != User.Role.DIALER_MANAGER:
            raise PermissionDenied("Dialer observability is available to Dialer Managers.")
        if not user.company_id:
            raise PermissionDenied("A company assignment is required.")

        key = str(request.query_params.get("window", "today")).strip().lower()
        timezone_name = getattr(user.branch, "timezone", None) or "America/New_York"
        local_tz = ZoneInfo(timezone_name)
        start_local, end_local = _observability_window(key, local_tz)

        # Mirror the inbound-list resolver's eligibility rules so outbound and
        # manual SALEs never appear as false observability errors.
        sales = (
            CallEvent.objects.filter(
                dialer__branch__company_id=user.company_id,
                dialer__is_closer=True,
                disposition__iexact="SALE",
            )
            .exclude(call_direction=CallEvent.Direction.OUTBOUND)
            .exclude(dial_method=CallEvent.DialMethod.MANUAL)
            .annotate(
                sale_at=Coalesce("call_date", "finalized_at", "received_at"),
                ingroup_key=Trim("closer_group"),
            )
            .filter(ingroup_key__gt="")
            .filter(sale_at__gte=start_local.astimezone(timezone.get_current_timezone()))
            .filter(sale_at__lt=end_local.astimezone(timezone.get_current_timezone()))
        )

        grouped_rows = list(
            sales.values(
                "dialer_id",
                "dialer__name",
                "ingroup_key",
                "inbound_list_name",
            )
            .annotate(count=Count("id"))
            .order_by("dialer__name", "closer_group", "inbound_list_name")
        )

        dialers = {}
        total_errors = 0
        for row in grouped_rows:
            dialer_id = str(row["dialer_id"])
            dialer = dialers.setdefault(
                dialer_id,
                {
                    "id": dialer_id,
                    "name": row["dialer__name"],
                    "sales": 0,
                    "error_count": 0,
                    "ingroups": {},
                    "errors": {},
                },
            )
            count = row["count"] or 0
            dialer["sales"] += count

            raw_list_name = (row["inbound_list_name"] or "").strip()
            is_error = not raw_list_name or raw_list_name.upper().startswith("ERROR:")
            if is_error:
                message = raw_list_name or "Unresolved list name"
                dialer["error_count"] += count
                dialer["errors"][message] = dialer["errors"].get(message, 0) + count
                total_errors += count

            ingroup_name = " ".join((row["ingroup_key"] or "").split())
            ingroup = dialer["ingroups"].setdefault(
                ingroup_name,
                {"name": ingroup_name, "sales": 0, "lists": {}},
            )
            ingroup["sales"] += count
            if not is_error:
                ingroup["lists"][raw_list_name] = (
                    ingroup["lists"].get(raw_list_name, 0) + count
                )

        payload_dialers = []
        for dialer in sorted(dialers.values(), key=lambda item: item["name"].casefold()):
            ingroups = []
            for ingroup in sorted(
                dialer["ingroups"].values(), key=lambda item: item["name"].casefold()
            ):
                ingroups.append(
                    {
                        "name": ingroup["name"],
                        "sales": ingroup["sales"],
                        "lists": [
                            {"name": list_name, "count": count}
                            for list_name, count in sorted(
                                ingroup["lists"].items(),
                                key=lambda item: (-item[1], item[0].casefold()),
                            )
                        ],
                    }
                )
            payload_dialers.append(
                {
                    "id": dialer["id"],
                    "name": dialer["name"],
                    "sales": dialer["sales"],
                    "error_count": dialer["error_count"],
                    "ingroups": ingroups,
                    "errors": [
                        {"message": message, "count": count}
                        for message, count in sorted(
                            dialer["errors"].items(),
                            key=lambda item: (-item[1], item[0].casefold()),
                        )
                    ],
                }
            )

        return Response(
            {
                "window": {
                    "key": key,
                    "label": DIALER_OBSERVABILITY_WINDOWS.get(key, key),
                    "from": start_local.isoformat(),
                    "to": end_local.isoformat(),
                    "timezone": timezone_name,
                },
                "totals": {
                    "sales": sum(item["sales"] for item in payload_dialers),
                    "dialers": len(payload_dialers),
                    "errors": total_errors,
                },
                "dialers": payload_dialers,
                "generated_at": timezone.now(),
            }
        )
