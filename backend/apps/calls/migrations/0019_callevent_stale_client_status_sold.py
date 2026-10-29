from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0018_critical_failure_score"),
    ]

    operations = [
        migrations.AddField(
            model_name="callevent",
            name="client_status",
            field=models.CharField(blank=True, max_length=160, null=True),
        ),
        migrations.AddField(
            model_name="callevent",
            name="sold",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="callevent",
            name="stale",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddIndex(
            model_name="callevent",
            index=models.Index(
                fields=["disposition", "stale", "received_at"],
                name="calls_stale_scan_idx",
            ),
        ),
    ]
