"""AI-specific conversation scope. Authorization is shared with CallLens analytics."""
import hashlib
import json
from apps.tenancy.models import QAProjectAssignment, Team
from apps.accounts.models import User
from apps.access.policy import require_management_access as require_ai_access
from apps.access.policy import permitted_management_reviews as permitted_reviews

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
