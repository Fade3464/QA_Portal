# Initial QA AI conversation and metadata-only audit tables.
import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name='AIConversation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('scope_digest', models.CharField(max_length=64)),
                ('title', models.CharField(default='New conversation', max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='ai_conversations', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at'],
                     'indexes': [models.Index(fields=['user', '-updated_at'], name='ai_conv_user_recent_idx')]},
        ),
        migrations.CreateModel(
            name='AIMessage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('role', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant')], max_length=10)),
                ('content', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                   related_name='messages', to='ai_assistant.aiconversation')),
            ],
            options={'ordering': ['created_at', 'pk'],
                     'indexes': [models.Index(fields=['conversation', 'created_at'], name='ai_msg_conversation_idx')]},
        ),
        migrations.CreateModel(
            name='AIToolAudit',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tool_name', models.CharField(max_length=90)),
                ('outcome', models.CharField(max_length=24)),
                ('elapsed_ms', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                   related_name='tool_audits', to='ai_assistant.aiconversation')),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL,
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={'indexes': [models.Index(fields=['created_at', 'tool_name'], name='ai_tool_audit_idx')]},
        ),
    ]
