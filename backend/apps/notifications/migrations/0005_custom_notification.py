from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_add_qa_report_returned_category")]

    operations = [
        migrations.AlterField(
            model_name="systemnotification",
            name="category",
            field=models.CharField(
                choices=[
                    ("unknown_team", "Unknown team"),
                    ("qa_report_ready", "QA report ready"),
                    ("qa_report_returned", "QA report returned"),
                    ("custom", "Custom notification"),
                ],
                max_length=40,
            ),
        ),
    ]
