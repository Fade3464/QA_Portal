from django.db import migrations


def assign_existing_dialer_managers(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    DialerCampaign = apps.get_model("tenancy", "DialerCampaign")
    QAProjectAssignment = apps.get_model("tenancy", "QAProjectAssignment")

    assignments = []
    managers = User.objects.filter(
        is_superuser=False,
        role="dialer_manager",
        company_id__isnull=False,
    ).values_list("id", "company_id")

    for user_id, company_id in managers.iterator():
        project_ids = DialerCampaign.objects.filter(
            dialer__branch__company_id=company_id,
        ).values_list("id", flat=True)
        assignments.extend(
            QAProjectAssignment(qa_id=user_id, dialer_campaign_id=project_id)
            for project_id in project_ids
        )
        if len(assignments) >= 1000:
            QAProjectAssignment.objects.bulk_create(
                assignments,
                ignore_conflicts=True,
                batch_size=1000,
            )
            assignments = []

    if assignments:
        QAProjectAssignment.objects.bulk_create(
            assignments,
            ignore_conflicts=True,
            batch_size=1000,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0012_dialer_multiple_fronter_mappings"),
    ]

    operations = [
        migrations.RunPython(assign_existing_dialer_managers, migrations.RunPython.noop),
    ]
