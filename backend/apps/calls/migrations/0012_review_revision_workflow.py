from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("calls", "0011_review_critical_error_evidence")]

    operations = [
        migrations.AlterField(
            model_name="review",
            name="status",
            field=models.CharField(
                choices=[
                    ("assigned", "Assigned"),
                    ("in_progress", "In progress"),
                    ("revision_required", "Revision required"),
                    ("completed", "Completed"),
                    ("disputed", "Disputed"),
                ],
                default="assigned",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="review",
            name="leader_status",
            field=models.CharField(
                choices=[
                    ("pending", "Needs review"),
                    ("acknowledged", "Reviewed"),
                    ("coaching_planned", "Coaching planned"),
                    ("coaching_completed", "Coaching completed"),
                    ("escalated", "Escalated"),
                    ("returned_to_qa", "Returned to QA"),
                    ("closed", "Closed"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="review",
            name="revision_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="review",
            name="revision_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="review",
            name="revision_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reviewworkflowevent",
            name="email_last_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="reviewworkflowevent",
            name="email_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reviewworkflowevent",
            name="email_status",
            field=models.CharField(
                choices=[
                    ("disabled", "Disabled"),
                    ("pending", "Pending"),
                    ("sent", "Sent"),
                    ("failed", "Failed"),
                ],
                default="disabled",
                max_length=16,
            ),
        ),
    ]
