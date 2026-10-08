from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ai_assistant', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='aimessage', name='evidence',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='aimessage', name='tools_used',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
