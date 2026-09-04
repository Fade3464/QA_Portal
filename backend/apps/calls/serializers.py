from rest_framework import serializers

from .models import CallEvent


class CallEventSerializer(serializers.ModelSerializer):
    dialer = serializers.CharField(source="dialer.name")
    team = serializers.UUIDField(source="team_id", allow_null=True)
    team_name = serializers.SerializerMethodField()
    recording_available = serializers.SerializerMethodField()

    class Meta:
        model = CallEvent
        fields = (
            "id",
            "received_at",
            "call_date",
            "call_id",
            "lead_id",
            "agent_user",
            "agent_name",
            "team",
            "team_name",
            "campaign",
            "phone_number",
            "disposition",
            "talk_time",
            "dialer",
            "recording_lookup_status",
            "recording_download_status",
            "recording_available",
        )

    def get_team_name(self, obj):
        return obj.team.name if obj.team_id else obj.team_name

    def get_recording_available(self, obj):
        return obj.recording_download_status == CallEvent.Status.DOWNLOADED and bool(
            obj.recording_path
        )
