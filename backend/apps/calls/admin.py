from django.contrib import admin

from .models import CallEvent, Review


@admin.register(CallEvent)
class CallEventAdmin(admin.ModelAdmin):
    list_display = (
        "call_id",
        "lead_id",
        "branch",
        "agent_name",
        "agent_user",
        "team",
        "campaign",
        "call_direction",
        "disposition",
        "recording_download_status",
        "received_at",
    )
    list_filter = (
        "branch__company",
        "branch",
        "dialer",
        "call_direction",
        "team",
        "disposition",
        "recording_download_status",
    )
    search_fields = (
        "call_id",
        "lead_id",
        "agent_name",
        "agent_user",
        "team_name",
        "phone_number",
    )
    readonly_fields = tuple(field.name for field in CallEvent._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        "call",
        "reviewer",
        "status",
        "score",
        "assigned_at",
        "completed_at",
    )
    list_filter = ("status", "reviewer__branch")
    search_fields = ("call__call_id", "call__lead_id", "reviewer__email")
