from django.db import migrations, models


def normalize_existing_sale_only_fields(apps, schema_editor):
    CallEvent = apps.get_model("calls", "CallEvent")
    # The sold flag existed one release before the editor. Enforce the new
    # business rule before adding database constraints so legacy/non-SALE rows
    # cannot block deployment.
    CallEvent.objects.exclude(disposition="SALE").update(
        sold=False,
        client_20_plus=False,
        client_30_plus=False,
        preset=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0019_callevent_stale_client_status_sold"),
    ]

    operations = [
        migrations.AddField(
            model_name="callevent",
            name="client_20_plus",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="callevent",
            name="client_30_plus",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="callevent",
            name="preset",
            field=models.CharField(blank=True, db_index=True, max_length=160, null=True),
        ),
        migrations.RunPython(
            normalize_existing_sale_only_fields,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="callevent",
            constraint=models.CheckConstraint(
                condition=models.Q(client_20_plus=False) | models.Q(disposition="SALE"),
                name="calls_20_plus_requires_sale",
            ),
        ),
        migrations.AddConstraint(
            model_name="callevent",
            constraint=models.CheckConstraint(
                condition=models.Q(client_30_plus=False) | models.Q(disposition="SALE"),
                name="calls_30_plus_requires_sale",
            ),
        ),
        migrations.AddConstraint(
            model_name="callevent",
            constraint=models.CheckConstraint(
                condition=models.Q(client_30_plus=False) | models.Q(client_20_plus=True),
                name="calls_30_plus_implies_20",
            ),
        ),
        migrations.AddConstraint(
            model_name="callevent",
            constraint=models.CheckConstraint(
                condition=models.Q(sold=False) | models.Q(disposition="SALE"),
                name="calls_sold_requires_sale",
            ),
        ),
        migrations.AddConstraint(
            model_name="callevent",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(preset__isnull=True)
                    | models.Q(preset="")
                    | models.Q(disposition="SALE")
                ),
                name="calls_preset_requires_sale",
            ),
        ),
    ]
