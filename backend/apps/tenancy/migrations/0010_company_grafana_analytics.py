from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0009_dialer_preset_lookup_credentials")]

    operations = [
        migrations.AddField(
            model_name="company",
            name="analytics_enabled",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="company",
            name="grafana_viewer_username",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="company",
            name="grafana_viewer_password_ciphertext",
            field=models.TextField(blank=True, editable=False),
        ),
        migrations.AddField(
            model_name="company",
            name="grafana_user_id",
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="company",
            name="grafana_synced_username",
            field=models.CharField(blank=True, editable=False, max_length=120),
        ),
        migrations.AddConstraint(
            model_name="company",
            constraint=models.UniqueConstraint(
                condition=models.Q(("analytics_enabled", True)),
                fields=("analytics_enabled",),
                name="single_analytics_company",
            ),
        ),
    ]
