from rest_framework import serializers

from .models import CallEvent


class CallEventSerializer(serializers.ModelSerializer):
    dialer = serializers.CharField(source="dialer.name")
    team = serializers.UUIDField(source="team_id", allow_null=True)
    team_name = serializers.SerializerMethodField()
    team_avatar = serializers.SerializerMethodField()
    recording_available = serializers.SerializerMethodField()
    project_name = serializers.CharField(read_only=True, allow_null=True)
    closecallid = serializers.CharField(source="close_call_id", read_only=True)
    xfercallid = serializers.CharField(source="xfer_call_id", read_only=True)
    group = serializers.CharField(source="closer_group", read_only=True)

    class Meta:
        model = CallEvent
        fields = (
            "id",
            "received_at",
            "call_date",
            "call_id",
            "closecallid",
            "xfercallid",
            "lead_id",
            "agent_user",
            "agent_name",
            "team",
            "team_name",
            "team_avatar",
            "campaign",
            "project_name",
            "group",
            "did_id",
            "did_pattern",
            "call_direction",
            "phone_number",
            "disposition",
            "talk_time",
            "termination_reason",
            "dialer",
            "recording_lookup_status",
            "recording_download_status",
            "recording_available",
        )

    def get_team_name(self, obj):
        return obj.team.name if obj.team_id else obj.team_name

    def get_team_avatar(self, obj):
        return obj.team.avatar if obj.team_id else ""

    def get_recording_available(self, obj):
        return obj.recording_download_status == CallEvent.Status.DOWNLOADED and bool(
            obj.recording_path
        )
