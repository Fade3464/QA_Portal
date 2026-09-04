import hashlib

from django.db import migrations


def queue_existing_unknown_teams(apps, schema_editor):
    CallEvent = apps.get_model("calls", "CallEvent")
    SystemNotification = apps.get_model("notifications", "SystemNotification")
    Team = apps.get_model("tenancy", "Team")

    groups = {}
    calls = (
        CallEvent.objects.filter(team__isnull=True)
        .exclude(team_name="")
        .select_related("branch")
        .order_by("received_at")
    )
    for event in calls.iterator(chunk_size=500):
        normalized_name = " ".join(event.team_name.split()).casefold()
        key = (event.branch_id, normalized_name)
        group = groups.setdefault(key, {"count": 0, "latest": event})
        group["count"] += 1
        group["latest"] = event

    for (branch_id, normalized_name), group in groups.items():
        latest = group["latest"]
        matching_team = next(
            (
                team
                for team in Team.objects.filter(branch_id=branch_id, is_active=True)
                if " ".join(team.name.split()).casefold() == normalized_name
            ),
            None,
        )
        if matching_team:
            CallEvent.objects.filter(
                branch_id=branch_id,
                team__isnull=True,
                team_name__iexact=matching_team.name,
            ).update(team=matching_team)
            continue

        digest = hashlib.sha256(f"{branch_id}:{normalized_name}".encode()).hexdigest()[:40]
        team_name = latest.team_name
        SystemNotification.objects.update_or_create(
            dedupe_key=f"unknown-team:{digest}",
            defaults={
                "category": "unknown_team",
                "severity": "warning",
                "title": f"Unknown team: {team_name}",
                "message": f'Calls for "{team_name}" are waiting for a team assignment in {latest.branch.name}.',
                "branch_id": branch_id,
                "call_id": latest.pk,
                "metadata": {
                    "team_name": team_name,
                    "normalized_team_name": normalized_name,
                    "latest_call_id": latest.call_id,
                    "latest_lead_id": latest.lead_id,
                    "agent_name": latest.agent_name,
                    "agent_user": latest.agent_user,
                },
                "occurrences": group["count"],
                "resolved_at": None,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]

    operations = [
        migrations.RunPython(
            queue_existing_unknown_teams,
            migrations.RunPython.noop,
        )
    ]
