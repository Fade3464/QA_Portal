from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0023_callevent_edited_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="callevent",
            name="inbound_list_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
