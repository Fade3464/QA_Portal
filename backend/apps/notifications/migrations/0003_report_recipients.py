from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_queue_existing_unknown_teams"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="systemnotification",
            name="category",
            field=models.CharField(
                choices=[
                    ("unknown_team", "Unknown team"),
                    ("qa_report_ready", "QA report ready"),
                ],
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="systemnotification",
            name="recipients",
            field=models.ManyToManyField(
                blank=True,
                related_name="system_notifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
