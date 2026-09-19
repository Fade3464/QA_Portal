from django.db import migrations


def assign_team_leaders_to_branch_projects(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    DialerCampaign = apps.get_model("tenancy", "DialerCampaign")
    ProjectAssignment = apps.get_model("tenancy", "QAProjectAssignment")

    campaigns_by_branch = {}
    for campaign_id, branch_id in DialerCampaign.objects.values_list(
        "id", "dialer__branch_id"
    ):
        campaigns_by_branch.setdefault(branch_id, []).append(campaign_id)

    assignments = []
    leaders = User.objects.filter(
        role="team_leader", is_superuser=False, branch__isnull=False
    ).values_list("id", "branch_id")
    for leader_id, branch_id in leaders:
        assignments.extend(
            ProjectAssignment(qa_id=leader_id, dialer_campaign_id=campaign_id)
            for campaign_id in campaigns_by_branch.get(branch_id, [])
        )
    ProjectAssignment.objects.bulk_create(
        assignments, batch_size=500, ignore_conflicts=True
    )


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0006_remove_dialer_allowed_recording_hosts")]

    operations = [
        migrations.RunPython(
            assign_team_leaders_to_branch_projects, migrations.RunPython.noop
        )
    ]
