from django.db import migrations
from django.utils import timezone


def normalize(value):
    return " ".join((value or "").split()).casefold()


def assign_team_leader_prefixes(apps, schema_editor):
    CallEvent = apps.get_model("calls", "CallEvent")
    SystemNotification = apps.get_model("notifications", "SystemNotification")
    Team = apps.get_model("tenancy", "Team")

    teams_by_branch = {}
    for team in Team.objects.filter(is_active=True).select_related("team_leader"):
        teams_by_branch.setdefault(team.branch_id, []).append(team)

    resolved_prefixes = set()
    for event in (
        CallEvent.objects.filter(team__isnull=True)
        .exclude(team_name="")
        .iterator(chunk_size=500)
    ):
        prefix = normalize(event.team_name)
        branch_teams = teams_by_branch.get(event.branch_id, [])
        team_matches = [team for team in branch_teams if normalize(team.name) == prefix]
        matches = team_matches or [
            team
            for team in branch_teams
            if normalize(team.team_leader.get_full_name() or team.team_leader.email)
            == prefix
        ]
        if len(matches) == 1:
            CallEvent.objects.filter(pk=event.pk).update(team_id=matches[0].pk)
            resolved_prefixes.add((event.branch_id, prefix))

    now = timezone.now()
    for branch_id, prefix in resolved_prefixes:
        SystemNotification.objects.filter(
            branch_id=branch_id,
            category="unknown_team",
            resolved_at__isnull=True,
            metadata__normalized_team_name=prefix,
        ).update(resolved_at=now, updated_at=now)


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0002_callevent_team_and_agent_name"),
        ("notifications", "0002_queue_existing_unknown_teams"),
    ]

    operations = [
        migrations.RunPython(
            assign_team_leader_prefixes,
            migrations.RunPython.noop,
        )
    ]
