from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("calls", "0014_review_criterion_applicability")]

    # Reports and workflow events are preserved; only the retired sender's
    # delivery metadata is removed. Back up existing delivery history first.
    operations = [
        migrations.RemoveField(model_name=model, name=field)
        for model in ("review", "reviewworkflowevent")
        for field in ("email_status", "email_sent_at", "email_last_error")
    ]
