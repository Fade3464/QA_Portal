from django.contrib import admin
from .models import AIConversation, AIMessage, AIToolAudit


@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at', 'updated_at')
    search_fields = ('user__email',)
    readonly_fields = ('id', 'user', 'title', 'scope_digest', 'created_at', 'updated_at')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AIMessage)
class AIMessageAdmin(admin.ModelAdmin):
    # Prompts may contain confidential summaries; do not render them in Django admin.
    list_display = ('id', 'conversation', 'role', 'created_at')
    exclude = ('content',)
    readonly_fields = ('id', 'conversation', 'role', 'created_at')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AIToolAudit)
class AIToolAuditAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'tool_name', 'outcome', 'elapsed_ms')
    list_filter = ('tool_name', 'outcome')
    readonly_fields = ('created_at', 'user', 'conversation', 'tool_name', 'outcome', 'elapsed_ms')
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
