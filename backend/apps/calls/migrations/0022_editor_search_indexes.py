from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("calls", "0021_callevent_finalized_at"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="callevent",
            index=models.Index(
                fields=["branch", "phone_number", "-call_date"],
                name="calls_ed_phone_date_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="callevent",
            index=models.Index(
                fields=["branch", "lead_id", "-call_date"],
                name="calls_ed_lead_date_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="callevent",
            index=models.Index(
                fields=["branch", "agent_user", "-call_date"],
                name="calls_ed_agent_date_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="callevent",
            index=models.Index(
                fields=["branch", "disposition", "-call_date"],
                name="calls_ed_dispo_date_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="callevent",
            index=models.Index(
                fields=["branch", "dialer", "campaign"],
                name="calls_ed_scope_idx",
            ),
        ),
    ]
