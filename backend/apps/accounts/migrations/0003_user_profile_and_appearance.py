from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_alter_authenticationevent_event")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="appearance_compact",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="appearance_mode",
            field=models.CharField(
                choices=[("light", "Light"), ("dark", "Dark"), ("system", "System")],
                default="system",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="appearance_preset",
            field=models.CharField(
                choices=[
                    ("calllens", "CallLens"),
                    ("ant_blue", "Ant Blue"),
                    ("geek_blue", "Geek Blue"),
                    ("purple", "Purple"),
                    ("cyan", "Cyan"),
                    ("emerald", "Emerald"),
                    ("magenta", "Magenta"),
                    ("volcano", "Volcano"),
                    ("gold", "Gold"),
                    ("neutral", "Neutral"),
                ],
                default="calllens",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="profile_picture",
            field=models.ImageField(blank=True, upload_to="profile-avatars/"),
        ),
    ]
