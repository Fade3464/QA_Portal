"""Authorization is resolved from Django, never from a model-supplied role/scope."""
import hashlib
import json
from rest_framework.exceptions import PermissionDenied
from apps.accounts.models import User
from apps.tenancy.models import QAProjectAssignment, Team
from apps.calls.views import scoped_reports

AI_ROLES = {User.Role.TEAM_LEADER, User.Role.PROJECT_MANAGER, User.Role.SUPERVISOR}


def require_ai_access(user):
    if user.is_authenticated and user.pk:
        # Honor permission revocations even in the middle of a multi-tool request.
        user.refresh_from_db(fields=['is_active', 'must_change_password', 'role',
                                     'is_superuser', 'company', 'branch'])
    if not user.is_authenticated or not user.is_active or user.must_change_password:
        raise PermissionDenied('AI access requires an active account and current password.')
    if user.is_superuser and user.role == User.Role.ADMINISTRATOR:
        return
    if user.role not in AI_ROLES or not user.company_id or not user.branch_id:
        raise PermissionDenied('AI insights are available to team leaders, project managers, supervisors and administrators.')
    if user.branch.company_id != user.company_id or not user.branch.is_active or not user.company.is_active:
        raise PermissionDenied('Invalid or inactive organizational assignment.')


def permitted_reviews(user):
    require_ai_access(user)
    # Reuse the authoritative report library scope, including project / team rules.
    return scoped_reports(user)


def scope_digest(user):
    """Invalidate historical conversation access after team/project/user changes."""
    require_ai_access(user)
    assigned = []
    teams = []
    if not user.is_superuser:
        assigned = list(QAProjectAssignment.objects.filter(qa=user).order_by('dialer_campaign_id').values_list('dialer_campaign_id', flat=True))
        if user.role == User.Role.TEAM_LEADER:
            teams = list(Team.objects.filter(team_leader=user).order_by('id').values_list('id', flat=True))
    snapshot = [str(user.pk), user.role, bool(user.is_superuser), str(user.company_id), str(user.branch_id),
                [str(value) for value in assigned], [str(value) for value in teams]]
    return hashlib.sha256(json.dumps(snapshot, separators=(',', ':')).encode()).hexdigest()
