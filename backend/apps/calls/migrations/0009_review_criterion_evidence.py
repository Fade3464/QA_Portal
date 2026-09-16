from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("calls", "0008_review_scorecard_workflow")]

    operations = [
        migrations.AddField(
            model_name="review",
            name="criterion_evidence",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
