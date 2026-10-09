from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ai_assistant', '0002_message_evidence')]

    operations = [
        migrations.AddField(model_name='aiconversation', name='context_state',
                            field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name='aimessage', name='interpretation',
                            field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name='aimessage', name='warnings',
                            field=models.JSONField(default=list, blank=True)),
    ]
