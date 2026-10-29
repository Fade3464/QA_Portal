from django.db import migrations, models
from django.utils import timezone
from django.utils.dateparse import parse_datetime


PROVISIONAL = {"NEW", "INCALL", "STALE"}


def backfill_finalized_at(apps, schema_editor):
    CallEvent = apps.get_model("calls", "CallEvent")
    batch = []
    queryset = CallEvent.objects.filter(finalized_at__isnull=True).iterator(chunk_size=500)

    for event in queryset:
        disposition = (event.disposition or "").upper()
        if disposition in PROVISIONAL or event.stale:
            continue

        finalized = None
        payload = event.raw_payload if isinstance(event.raw_payload, dict) else {}
        raw = payload.get("ingested_finalized_at")
        if raw:
            parsed = parse_datetime(str(raw))
            if parsed is not None:
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                finalized = parsed

        # Older rows predate explicit lifecycle-finalization tracking. Their
        # first receipt is the safest deterministic approximation.
        event.finalized_at = finalized or event.received_at
        batch.append(event)
        if len(batch) >= 500:
            CallEvent.objects.bulk_update(batch, ["finalized_at"], batch_size=500)
            batch.clear()

    if batch:
        CallEvent.objects.bulk_update(batch, ["finalized_at"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0020_callevent_client_duration_preset"),
    ]

    operations = [
        migrations.AddField(
            model_name="callevent",
            name="finalized_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_finalized_at, migrations.RunPython.noop),
    ]
