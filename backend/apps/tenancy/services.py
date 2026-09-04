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
