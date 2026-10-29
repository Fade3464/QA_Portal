from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0005_custom_notification"),
    ]

    operations = [
        migrations.AlterField(
            model_name="systemnotification",
            name="category",
            field=models.CharField(
                choices=[
                    ("unknown_team", "Unknown team"),
                    ("qa_report_ready", "QA report ready"),
                    ("qa_report_returned", "QA report returned"),
                    ("missing_preset", "Missing SALE preset"),
                    ("custom", "Custom notification"),
                ],
                max_length=40,
            ),
        ),
    ]
