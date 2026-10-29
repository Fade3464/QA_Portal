from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0008_use_new_york_timezone"),
    ]

    operations = [
        migrations.AddField(
            model_name="dialer",
            name="preset_lookup_password_ciphertext",
            field=models.TextField(blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="dialer",
            name="preset_lookup_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="dialer",
            name="preset_lookup_username",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="dialer",
            name="preset_lookup_verify_tls",
            field=models.BooleanField(default=True),
        ),
    ]
