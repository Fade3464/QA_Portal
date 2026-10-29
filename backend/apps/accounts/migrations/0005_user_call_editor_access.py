from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_alter_user_appearance_preset"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="call_editor_access",
            field=models.BooleanField(default=False),
        ),
    ]
