from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0005_team_avatar")]

    operations = [
        migrations.RemoveField(
            model_name="dialer",
            name="allowed_recording_hosts",
        ),
    ]
