from django.db import migrations, models


def backfill_dial_method(apps, schema_editor):
    CallEvent = apps.get_model("calls", "CallEvent")
    pending = []
    for event in (
        CallEvent.objects.all()
        .only("id", "call_id", "call_direction", "dial_method")
        .iterator(chunk_size=1000)
    ):
        call_id = (event.call_id or "").strip().upper()
        if event.call_direction != "OUTBOUND":
            event.dial_method = "N/A"
        elif call_id.startswith("M"):
            event.dial_method = "MANUAL"
        elif call_id.startswith("V"):
            event.dial_method = "AUTO"
        else:
            event.dial_method = "UNKNOWN"
        pending.append(event)
        if len(pending) == 1000:
            CallEvent.objects.bulk_update(pending, ["dial_method"], batch_size=1000)
            pending.clear()
    if pending:
        CallEvent.objects.bulk_update(pending, ["dial_method"], batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [("calls", "0005_callevent_xfer_call_id_and_more")]

    operations = [
        migrations.AddField(
            model_name="callevent",
            name="dial_method",
            field=models.CharField(
                choices=[
                    ("AUTO", "Auto Dial"),
                    ("MANUAL", "Manual Dial"),
                    ("UNKNOWN", "Unknown"),
                    ("N/A", "Not Applicable"),
                ],
                db_index=True,
                default="UNKNOWN",
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_dial_method, migrations.RunPython.noop),
    ]
