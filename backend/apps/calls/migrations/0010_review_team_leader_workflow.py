import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0009_review_criterion_evidence"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="coaching_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="review",
            name="leader_closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="review",
            name="leader_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="review",
            name="leader_status",
            field=models.CharField(
                choices=[
                    ("pending", "Needs review"),
                    ("acknowledged", "Reviewed"),
                    ("coaching_planned", "Coaching planned"),
                    ("coaching_completed", "Coaching completed"),
                    ("escalated", "Escalated"),
                    ("closed", "Closed"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="review",
            name="leader_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ReviewWorkflowEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("status_changed", "Status changed"),
                            ("note_added", "Note added"),
                        ],
                        max_length=24,
                    ),
                ),
                ("from_status", models.CharField(blank=True, max_length=24)),
                ("to_status", models.CharField(blank=True, max_length=24)),
                ("note", models.TextField(blank=True)),
                ("coaching_due_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="review_workflow_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "review",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflow_events",
                        to="calls.review",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["team_leader", "leader_status", "-completed_at"],
                name="review_leader_work_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="reviewworkflowevent",
            index=models.Index(
                fields=["review", "-created_at"],
                name="review_workflow_event_idx",
            ),
        ),
    ]
