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


class ProjectPerformanceView(APIView):
    """Decision-focused QA performance for the projects visible to the user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_superuser and request.user.role not in {
            User.Role.PROJECT_MANAGER,
            User.Role.SUPERVISOR,
        }:
            raise PermissionDenied("Project performance is available to management users.")

        try:
            days = int(request.query_params.get("days", "30"))
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

        project = request.query_params.get("project", "").strip()
        if project and project not in available_projects:
            raise ValidationError({"project": "Choose a project assigned to you."})
        dialer_id = request.query_params.get("dialer", "").strip()
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
