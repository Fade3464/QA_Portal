from rest_framework import serializers

from .models import CallEvent


class CallEventSerializer(serializers.ModelSerializer):
    dialer = serializers.CharField(source="dialer.name")
    phone_number = serializers.SerializerMethodField()
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
            "campaign",
            "phone_number",
            "disposition",
            "talk_time",
            "dialer",
            "recording_lookup_status",
            "recording_download_status",
            "recording_available",
        )

    def get_phone_number(self, obj):
        value = obj.phone_number
        return f"•••• {value[-4:]}" if len(value) > 4 else value

    def get_recording_available(self, obj):
        return obj.recording_download_status == CallEvent.Status.DOWNLOADED and bool(
            obj.recording_path
        )
