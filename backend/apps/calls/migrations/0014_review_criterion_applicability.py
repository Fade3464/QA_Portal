from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("calls", "0013_review_short_call_evaluation"),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="criterion_applicability",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
