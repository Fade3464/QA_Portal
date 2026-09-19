from django.db import migrations, models


def initialize_existing_reviews(apps, schema_editor):
    Review = apps.get_model("calls", "Review")
    applicability = {
        key: "applicable"
        for key in (
            "opening",
            "communication",
            "discovery",
            "presentation",
            "objection_handling",
            "sales_closing",
            "compliance",
            "crm_call_control",
        )
    }
    for review in Review.objects.all().iterator():
        review.category_applicability = applicability
        review.applicable_points = 100
        review.coverage = 100
        review.coverage_tier = "full"
        review.earned_points = review.score
        review.save(
            update_fields=[
                "category_applicability",
                "applicable_points",
                "coverage",
                "coverage_tier",
                "earned_points",
            ]
        )


class Migration(migrations.Migration):
    dependencies = [("calls", "0012_review_revision_workflow")]

    operations = [
        migrations.AlterField(
            model_name="review",
            name="rating",
            field=models.CharField(
                blank=True,
                choices=[
                    ("not_evaluable", "Not Evaluable"),
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
        migrations.AlterField(
            model_name="review",
            name="outcome",
            field=models.CharField(
                blank=True,
                choices=[
                    ("not_evaluable", "Not Evaluable"),
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
            name="evaluation_type",
            field=models.CharField(
                choices=[
                    ("full", "Full call"),
                    ("partial", "Partial call"),
                    ("not_evaluable", "Not evaluable"),
                    ("agent_premature", "Agent ended early"),
                ],
                default="full",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="review",
            name="evaluation_reason",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="review",
            name="category_applicability",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="review",
            name="category_applicability_reasons",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="review",
            name="earned_points",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="review",
            name="applicable_points",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="review",
            name="coverage",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="review",
            name="coverage_tier",
            field=models.CharField(
                blank=True,
                choices=[
                    ("insufficient", "Insufficient interaction"),
                    ("limited", "Limited coverage"),
                    ("partial", "Partial coverage"),
                    ("full", "Full coverage"),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(initialize_existing_reviews, migrations.RunPython.noop),
    ]
