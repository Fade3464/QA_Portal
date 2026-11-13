def normalize_team_identity(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def resolve_team_prefix(branch, prefix: str):
    """Resolve a VICIdial prefix by team name, then unambiguous leader name."""
    from .models import Team

    normalized_prefix = normalize_team_identity(prefix)
    if not normalized_prefix:
        return None

    teams = list(
        Team.objects.filter(branch=branch, is_active=True).select_related(
            "team_leader"
        )
    )
    for team in teams:
        if normalize_team_identity(team.name) == normalized_prefix:
            return team

    leader_matches = [
        team
        for team in teams
        if normalize_team_identity(team.team_leader.full_name) == normalized_prefix
    ]
    return leader_matches[0] if len(leader_matches) == 1 else None


def company_projects(user):
    """All dialer projects belonging to a user's company."""
    from .models import DialerCampaign

    if not getattr(user, "company_id", None):
        return DialerCampaign.objects.none()
    return DialerCampaign.objects.filter(
        dialer__branch__company_id=user.company_id,
    ).select_related("dialer", "dialer__branch")


def sync_dialer_manager_project_access(user) -> int:
    """Keep a Dialer Manager mapped to every project in their company.

    This is deliberately company-wide rather than branch-wide. Existing stale
    assignments are removed if the manager changes company, and current company
    projects are inserted idempotently.
    """
    from apps.accounts.models import User
    from .models import QAProjectAssignment

    if (
        getattr(user, "is_superuser", False)
        or getattr(user, "role", None) != User.Role.DIALER_MANAGER
        or not getattr(user, "company_id", None)
    ):
        return 0

    project_ids = list(company_projects(user).values_list("pk", flat=True))
    assignments = QAProjectAssignment.objects.filter(qa=user)
    if project_ids:
        assignments.exclude(dialer_campaign_id__in=project_ids).delete()
    else:
        assignments.delete()

    QAProjectAssignment.objects.bulk_create(
        [
            QAProjectAssignment(qa=user, dialer_campaign_id=project_id)
            for project_id in project_ids
        ],
        ignore_conflicts=True,
        batch_size=500,
    )
    return len(project_ids)


def sync_campaign_dialer_manager_access(campaign) -> int:
    """Map one dialer project to every Dialer Manager in its company."""
    from apps.accounts.models import User
    from .models import QAProjectAssignment

    company_id = campaign.dialer.branch.company_id
    managers = list(
        User.objects.filter(
            is_superuser=False,
            role=User.Role.DIALER_MANAGER,
            company_id=company_id,
        ).values_list("pk", flat=True)
    )

    # If a dialer was moved to another company, remove stale manager ownership
    # for this campaign before assigning the managers of its current company.
    QAProjectAssignment.objects.filter(
        dialer_campaign=campaign,
        qa__role=User.Role.DIALER_MANAGER,
    ).exclude(qa_id__in=managers).delete()

    QAProjectAssignment.objects.bulk_create(
        [
            QAProjectAssignment(qa_id=manager_id, dialer_campaign=campaign)
            for manager_id in managers
        ],
        ignore_conflicts=True,
        batch_size=500,
    )
    return len(managers)
