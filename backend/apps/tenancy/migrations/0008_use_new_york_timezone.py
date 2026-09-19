from django.db import migrations, models


def set_new_york_timezone(apps, schema_editor):
    Branch = apps.get_model("tenancy", "Branch")
    Branch.objects.exclude(timezone="America/New_York").update(
        timezone="America/New_York"
    )


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0007_assign_team_leaders_to_branch_projects")]

    operations = [
        migrations.AlterField(
            model_name="branch",
            name="timezone",
            field=models.CharField(
                choices=[("America/New_York", "Eastern Time (New York)")],
                default="America/New_York",
                max_length=64,
            ),
        ),
        migrations.RunPython(set_new_york_timezone, migrations.RunPython.noop),
    ]
