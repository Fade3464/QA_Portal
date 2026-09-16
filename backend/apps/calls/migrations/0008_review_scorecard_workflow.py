import django.db.models.deletion

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0007_analysispresence"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="coaching_plan",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="review",
            name="critical_errors",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="review",
            name="email_last_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="review",
            name="email_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="review",
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
        migrations.AddField(
            model_name="review",
            name="expected_behavior",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="review",
            name="feedback_summary",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="review",
            name="improvement_areas",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="review",
            name="outcome",
            field=models.CharField(
                blank=True,
                choices=[
                    ("exceeds_expectations", "Exceeds Expectations"),
                    ("meets_expectations", "Meets Expectations"),
                    ("meets_minimum_standard", "Meets Minimum Standard"),
                    ("coaching_required", "Coaching Required"),
                    ("performance_action_required", "Performance Action Required"),
                    ("immediate_escalation", "Immediate Escalation"),
                ],
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="review",
            name="rating",
            field=models.CharField(
                blank=True,
                choices=[
                    ("excellent", "Excellent"),
                    ("very_good", "Very Good"),
                    ("good", "Good"),
                    ("needs_improvement", "Needs Improvement"),
                    ("unsatisfactory", "Unsatisfactory"),
                    ("automatic_fail", "Automatic Fail"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="review",
            name="scorecard_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="review",
            name="scorecard_version",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="review",
            name="scores",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="review",
            name="strengths",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="review",
            name="team_leader",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="qa_reports_received",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["reviewer", "status", "-assigned_at"],
                name="review_owner_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["team_leader", "status", "-completed_at"],
                name="review_leader_status_idx",
            ),
        ),
    ]
