"""Minimum conversation persistence. Never persist tool responses or raw call/customer data."""
import uuid
from django.conf import settings
from django.db import models


class AIConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_conversations')
    scope_digest = models.CharField(max_length=64)
    title = models.CharField(max_length=120, default='New conversation')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['user', '-updated_at'], name='ai_conv_user_recent_idx')]


class AIMessage(models.Model):
    class Role(models.TextChoices):
        USER = 'user', 'User'
        ASSISTANT = 'assistant', 'Assistant'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    # Scoped references only; no raw tool output or customer records stored.
    evidence = models.JSONField(default=list, blank=True)
    tools_used = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        indexes = [models.Index(fields=['conversation', 'created_at'], name='ai_msg_conversation_idx')]


class AIToolAudit(models.Model):
    """Metadata only: no natural-language prompts, customer data, or tool output."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(AIConversation, null=True, on_delete=models.SET_NULL, related_name='tool_audits')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    tool_name = models.CharField(max_length=90)
    outcome = models.CharField(max_length=24)
    elapsed_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['created_at', 'tool_name'], name='ai_tool_audit_idx')]
