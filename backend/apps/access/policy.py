"""Central management authorization boundary for analytics and AI.

All callers resolve scope from authenticated Django users, not model parameters.
"""
from rest_framework.exceptions import PermissionDenied
from apps.accounts.models import User
from apps.access.report_scope import scoped_reports

AI_ROLES = {User.Role.TEAM_LEADER, User.Role.PROJECT_MANAGER, User.Role.SUPERVISOR}


def require_management_access(user):
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


def permitted_management_reviews(user):
    require_management_access(user)
    # Reuse the authoritative report library scope, including project / team rules.
    return scoped_reports(user)


