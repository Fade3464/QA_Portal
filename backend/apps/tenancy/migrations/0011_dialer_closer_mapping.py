from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0010_company_grafana_analytics")]

    operations = [
        migrations.AddField(
            model_name="dialer",
            name="is_closer",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="dialer",
            name="fronter_dialer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mapped_closer_dialers",
                to="tenancy.dialer",
            ),
        ),
        migrations.AddField(
            model_name="dialer",
            name="fronter_ingroup_name",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
