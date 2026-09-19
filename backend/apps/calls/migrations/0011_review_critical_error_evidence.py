from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("calls", "0010_review_team_leader_workflow")]

    operations = [
        migrations.AddField(
            model_name="review",
            name="critical_error_evidence",
            field=models.JSONField(blank=True, default=dict),
        )
    ]
