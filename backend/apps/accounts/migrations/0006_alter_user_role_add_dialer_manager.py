from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_user_call_editor_access"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("qa", "QA Analyst"),
                    ("team_leader", "Team Leader"),
                    ("project_manager", "Project Manager"),
                    ("supervisor", "Supervisor"),
                    ("dialer_manager", "Dialer Manager"),
                    ("administrator", "System Administrator"),
                ],
                max_length=32,
            ),
        ),
    ]
