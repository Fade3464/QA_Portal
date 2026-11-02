from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("calls", "0022_editor_search_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="callevent",
            name="edited_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
