from django.core.validators import RegexValidator
from django.db import migrations, models


TEAM_AVATARS = {
    "annihilators": "local_fire_department",
    "med legends": "health_and_safety",
    "spartans": "shield",
    "titans": "workspace_premium",
    "warriors": "swords",
}


def assign_team_avatars(apps, schema_editor):
    Team = apps.get_model("tenancy", "Team")
    for team in Team.objects.all().only("id", "name"):
        avatar = TEAM_AVATARS.get(" ".join(team.name.split()).casefold())
        if avatar:
            Team.objects.filter(pk=team.pk).update(avatar=avatar)


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0004_qaprojectassignment")]

    operations = [
        migrations.AddField(
            model_name="team",
            name="avatar",
            field=models.CharField(
                default="groups",
                max_length=80,
                validators=[
                    RegexValidator(
                        regex="^[a-z0-9_]+$",
                        message="Choose a valid Material Symbol avatar.",
                    )
                ],
            ),
        ),
        migrations.RunPython(assign_team_avatars, migrations.RunPython.noop),
    ]
