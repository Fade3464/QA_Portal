import uuid

from django.db import migrations, models
import django.db.models.deletion


def migrate_existing_mapping(apps, schema_editor):
    Dialer = apps.get_model("tenancy", "Dialer")
    DialerFronterMapping = apps.get_model("tenancy", "DialerFronterMapping")

    seen_fronters = {}
    for closer in Dialer.objects.exclude(fronter_dialer_id=None).iterator():
        fronter_id = closer.fronter_dialer_id
        if fronter_id in seen_fronters:
            first_closer_id = seen_fronters[fronter_id]
            raise RuntimeError(
                "Cannot migrate closer/fronter mappings because fronter dialer "
                f"{fronter_id} is mapped to more than one closer "
                f"({first_closer_id} and {closer.pk}). Remove the duplicate mapping first."
            )
        seen_fronters[fronter_id] = closer.pk
        DialerFronterMapping.objects.create(
            id=uuid.uuid4(),
            closer_dialer_id=closer.pk,
            fronter_dialer_id=fronter_id,
            ingroup_name=(closer.fronter_ingroup_name or "").strip(),
        )


def reverse_existing_mapping(apps, schema_editor):
    Dialer = apps.get_model("tenancy", "Dialer")
    DialerFronterMapping = apps.get_model("tenancy", "DialerFronterMapping")

    for closer in Dialer.objects.filter(is_closer=True).iterator():
        mapping = DialerFronterMapping.objects.filter(
            closer_dialer_id=closer.pk
        ).order_by("created_at").first()
        if mapping:
            closer.fronter_dialer_id = mapping.fronter_dialer_id
            closer.fronter_ingroup_name = mapping.ingroup_name
            closer.save(update_fields=["fronter_dialer", "fronter_ingroup_name"])


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0011_dialer_closer_mapping")]

    operations = [
        migrations.CreateModel(
            name="DialerFronterMapping",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("ingroup_name", models.CharField(max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "closer_dialer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fronter_mappings",
                        to="tenancy.dialer",
                    ),
                ),
                (
                    "fronter_dialer",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="closer_mapping",
                        to="tenancy.dialer",
                    ),
                ),
            ],
            options={
                "ordering": ["closer_dialer__name", "fronter_dialer__name"],
            },
        ),
        migrations.RunPython(migrate_existing_mapping, reverse_existing_mapping),
        migrations.RemoveField(
            model_name="dialer",
            name="fronter_dialer",
        ),
        migrations.RemoveField(
            model_name="dialer",
            name="fronter_ingroup_name",
        ),
    ]
