from django.contrib import admin

from .models import CallEvent, Review, ReviewWorkflowEvent


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
        "dial_method",
        "disposition",
        "recording_download_status",
        "received_at",
    )
    list_filter = (
        "branch__company",
        "branch",
        "dialer",
        "call_direction",
        "dial_method",
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
        "rating",
        "outcome",
        "leader_status",
        "team_leader",
        "assigned_at",
        "completed_at",
    )
    list_filter = (
        "status",
        "leader_status",
        "rating",
        "outcome",
        "reviewer__branch",
    )
    search_fields = ("call__call_id", "call__lead_id", "reviewer__email")


@admin.register(ReviewWorkflowEvent)
class ReviewWorkflowEventAdmin(admin.ModelAdmin):
    list_display = (
        "review",
        "event_type",
        "actor",
        "from_status",
        "to_status",
        "created_at",
    )
    list_filter = ("event_type", "to_status")
    search_fields = ("review__call__call_id", "actor__email", "note")
    readonly_fields = tuple(field.name for field in ReviewWorkflowEvent._meta.fields)

    def has_add_permission(self, request):
        return False
