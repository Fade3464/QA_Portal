from decimal import Decimal

from django.db import migrations, models


def apply_critical_failure_scores(apps, schema_editor):
    Review = apps.get_model("calls", "Review")
    reports = Review.objects.using(schema_editor.connection.alias)
    # Capture the previous score in the same UPDATE that applies the override.
    # Answers, evidence, coverage, timestamps and workflow remain unchanged.
    reports.filter(models.Q(score__isnull=False) | ~models.Q(critical_errors=[])).update(
        scorecard_score=models.F("score"),
        score=models.Case(
            models.When(~models.Q(critical_errors=[]), then=models.Value(Decimal("0.00"))),
            default=models.F("score"),
            output_field=models.DecimalField(max_digits=5, decimal_places=2),
        ),
    )
    if schema_editor.connection.vendor == "postgresql":
        # Drain deferred FK checks before adding the constraint, atomically.
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def restore_critical_scorecard_scores(apps, schema_editor):
    Review = apps.get_model("calls", "Review")
    Review.objects.using(schema_editor.connection.alias).exclude(critical_errors=[]).update(
        score=models.F("scorecard_score"),
    )
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    dependencies = [("calls", "0017_critical_is_evaluable")]

    operations = [
        migrations.AddField(
            model_name="review",
            name="scorecard_score",
            field=models.DecimalField(
                max_digits=5, decimal_places=2, null=True, blank=True,
                help_text="Normalized score before the critical-failure override.",
                editable=False,
            ),
        ),
        migrations.RunPython(apply_critical_failure_scores, restore_critical_scorecard_scores),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(status__in=["completed", "disputed"])
                    | models.Q(critical_errors=[])
                    | (models.Q(score__isnull=False) & models.Q(score=0))
                ),
                name="review_critical_final_score_zero",
            ),
        ),
    ]
