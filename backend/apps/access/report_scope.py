"""Single authoritative report-visibility policy for HTTP, dashboards and AI.

Never broaden this queryset using caller-controlled parameters.
"""
from django.db.models import Exists, OuterRef, Subquery
from apps.accounts.models import User
from apps.tenancy.models import DialerCampaign, QAProjectAssignment
from apps.calls.models import Review

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


def scoped_reports(user):
    queryset = _report_base_queryset()
    if user.is_superuser:
        return queryset
    if user.role == User.Role.QA:
        return queryset.filter(reviewer=user)
    if user.role == User.Role.SUPERVISOR:
        if not user.company_id or not user.branch_id:
            return queryset.none()
        return queryset.filter(
            call__branch_id=user.branch_id,
            call__branch__company_id=user.company_id,
            call__dialer__branch_id=user.branch_id,
        )
    completed = (Review.Status.COMPLETED, Review.Status.DISPUTED)
    if user.role == User.Role.TEAM_LEADER:
        allowed_project = QAProjectAssignment.objects.filter(
            qa=user,
            dialer_campaign__dialer_id=OuterRef("call__dialer_id"),
            dialer_campaign__campaign__iexact=OuterRef("call__campaign"),
        )
        return (
            queryset.filter(team_leader=user, status__in=completed)
            .exclude(evaluation_type=Review.EvaluationType.ZERO_DEFECT)
            .annotate(_project_allowed=Exists(allowed_project))
            .filter(_project_allowed=True)
        )
    if user.role == User.Role.PROJECT_MANAGER:
        allowed_project = QAProjectAssignment.objects.filter(
            qa=user,
            dialer_campaign__dialer_id=OuterRef("call__dialer_id"),
            dialer_campaign__campaign__iexact=OuterRef("call__campaign"),
        )
        return (
            queryset.filter(call__branch_id=user.branch_id)
            .annotate(_project_allowed=Exists(allowed_project))
            .filter(_project_allowed=True)
        )
    return queryset.filter(call__branch_id=user.branch_id, status__in=completed)


