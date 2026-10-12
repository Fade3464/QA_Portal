from django.db import migrations, models


def repair_conflicting_reviews(apps, schema_editor):
    Review = apps.get_model("calls", "Review")
    critical = Review.objects.using(schema_editor.connection.alias).exclude(critical_errors=[])
    # Preserve violations, evidence, scores and review workflow. Partial makes no
    # claim that the whole call was scored, including short critical failures.
    critical.filter(evaluation_type="not_evaluable").update(
        evaluation_type="partial", evaluation_reason="",
    )
    critical.filter(
        models.Q(rating="not_evaluable") | models.Q(outcome="not_evaluable")
    ).update(rating="automatic_fail", outcome="immediate_escalation")
    if schema_editor.connection.vendor == "postgresql":
        # Drain deferred FK checks created by the repair before ALTER TABLE.
        # Keep the repair and invariant atomic rather than leaving a gap between
        # a committed data migration and the new constraint.
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


class Migration(migrations.Migration):
    dependencies = [("calls", "0016_alter_review_evaluation_type_alter_review_outcome")]

    operations = [
        migrations.RunPython(repair_conflicting_reviews, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.CheckConstraint(
                condition=models.Q(critical_errors=[]) | (
                    ~models.Q(evaluation_type="not_evaluable")
                    & ~models.Q(rating="not_evaluable")
                    & ~models.Q(outcome="not_evaluable")
                ),
                name="review_critical_is_evaluable",
            ),
        ),
    ]
