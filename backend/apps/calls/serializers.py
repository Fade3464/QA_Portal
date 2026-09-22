from rest_framework import serializers

from .models import CallEvent, Review, ReviewWorkflowEvent
from .scorecard import (
    CRITICAL_ERRORS,
    CATEGORY_REASON_VALUES,
    calculate_evaluation,
    calculate_score,
    validate_criterion_evidence,
    validate_critical_error_evidence,
)


class ReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.CharField(source="reviewer.full_name", read_only=True)
    team_leader_name = serializers.CharField(
        source="team_leader.full_name", read_only=True, allow_null=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    rating_label = serializers.CharField(source="get_rating_display", read_only=True)
    outcome_label = serializers.CharField(source="get_outcome_display", read_only=True)
    leader_status_label = serializers.CharField(
        source="get_leader_status_display", read_only=True
    )
    scores = serializers.DictField(required=False)
    category_applicability = serializers.DictField(required=False)
    category_applicability_reasons = serializers.DictField(required=False)
    criterion_applicability = serializers.DictField(required=False)
    criterion_evidence = serializers.DictField(required=False)
    critical_error_evidence = serializers.DictField(required=False)
    critical_errors = serializers.ListField(
        child=serializers.ChoiceField(choices=CRITICAL_ERRORS), required=False
    )

    class Meta:
        model = Review
        fields = (
            "id",
            "status",
            "status_label",
            "score",
            "evaluation_type",
            "evaluation_reason",
            "category_applicability",
            "category_applicability_reasons",
            "criterion_applicability",
            "earned_points",
            "applicable_points",
            "coverage",
            "coverage_tier",
            "scorecard_version",
            "scorecard_snapshot",
            "scores",
            "criterion_evidence",
            "critical_errors",
            "critical_error_evidence",
            "rating",
            "rating_label",
            "outcome",
            "outcome_label",
            "feedback_summary",
            "strengths",
            "improvement_areas",
            "expected_behavior",
            "coaching_plan",
            "reviewer",
            "reviewer_name",
            "team_leader",
            "team_leader_name",
            "assigned_at",
            "completed_at",
            "email_status",
            "email_sent_at",
            "leader_status",
            "leader_status_label",
            "coaching_due_at",
            "leader_reviewed_at",
            "leader_closed_at",
            "leader_updated_at",
            "revision_requested_at",
            "revision_reason",
            "revision_count",
        )
        read_only_fields = (
            "id",
            "status",
            "score",
            "earned_points",
            "applicable_points",
            "coverage",
            "coverage_tier",
            "scorecard_version",
            "scorecard_snapshot",
            "rating",
            "outcome",
            "reviewer",
            "team_leader",
            "assigned_at",
            "completed_at",
            "email_status",
            "email_sent_at",
            "leader_status",
            "coaching_due_at",
            "leader_reviewed_at",
            "leader_closed_at",
            "leader_updated_at",
            "revision_requested_at",
            "revision_reason",
            "revision_count",
        )

    def validate_scores(self, value):
        calculate_score(value, require_complete=False)
        return value

    def validate_evaluation_reason(self, value):
        if value and value not in CATEGORY_REASON_VALUES:
            raise serializers.ValidationError("Select a supported call outcome reason.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = self.instance
        calculate_evaluation(
            attrs.get("scores", instance.scores if instance else {}),
            evaluation_type=attrs.get(
                "evaluation_type",
                instance.evaluation_type if instance else Review.EvaluationType.FULL,
            ),
            category_applicability=attrs.get(
                "category_applicability",
                instance.category_applicability if instance else {},
            ),
            category_applicability_reasons=attrs.get(
                "category_applicability_reasons",
                instance.category_applicability_reasons if instance else {},
            ),
            criterion_applicability=attrs.get(
                "criterion_applicability",
                instance.criterion_applicability if instance else {},
            ),
            require_complete=False,
        )
        return attrs

    def validate_criterion_evidence(self, value):
        duration = self.instance.call.talk_time if self.instance else None
        return validate_criterion_evidence(value, duration_seconds=duration)

    def validate_critical_error_evidence(self, value):
        duration = self.instance.call.talk_time if self.instance else None
        return validate_critical_error_evidence(value, duration_seconds=duration)


class ReviewListSerializer(ReviewSerializer):
    call_id = serializers.UUIDField(read_only=True)
    phone_number = serializers.CharField(source="call.phone_number", read_only=True)
    agent_name = serializers.SerializerMethodField()
    agent_user = serializers.CharField(source="call.agent_user", read_only=True)
    team_name = serializers.SerializerMethodField()
    project_name = serializers.CharField(read_only=True, allow_null=True)
    call_date = serializers.DateTimeField(source="call.call_date", read_only=True)

    class Meta(ReviewSerializer.Meta):
        fields = ReviewSerializer.Meta.fields + (
            "call_id",
            "phone_number",
            "agent_name",
            "agent_user",
            "team_name",
            "project_name",
            "call_date",
        )

    def get_agent_name(self, obj):
        return obj.call.agent_name or obj.call.agent_user

    def get_team_name(self, obj):
        return obj.call.team.name if obj.call.team_id else obj.call.team_name


class ReviewWorkflowEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True)
    event_type_label = serializers.CharField(
        source="get_event_type_display", read_only=True
    )
    from_status_label = serializers.SerializerMethodField()
    to_status_label = serializers.SerializerMethodField()

    class Meta:
        model = ReviewWorkflowEvent
        fields = (
            "id",
            "event_type",
            "event_type_label",
            "actor",
            "actor_name",
            "from_status",
            "from_status_label",
            "to_status",
            "to_status_label",
            "note",
            "coaching_due_at",
            "email_status",
            "email_sent_at",
            "created_at",
        )

    @staticmethod
    def _status_label(value):
        return dict(Review.LeaderStatus.choices).get(value, value)

    def get_from_status_label(self, obj):
        return self._status_label(obj.from_status)

    def get_to_status_label(self, obj):
        return self._status_label(obj.to_status)


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
    reservation = serializers.SerializerMethodField()

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
            "dial_method",
            "phone_number",
            "disposition",
            "talk_time",
            "termination_reason",
            "dialer",
            "recording_lookup_status",
            "recording_download_status",
            "recording_available",
            "reservation",
        )

    def get_team_name(self, obj):
        return obj.team.name if obj.team_id else obj.team_name

    def get_team_avatar(self, obj):
        return obj.team.avatar if obj.team_id else ""

    def get_recording_available(self, obj):
        return obj.recording_download_status == CallEvent.Status.DOWNLOADED and bool(
            obj.recording_path
        )

    def get_reservation(self, obj):
        try:
            review = obj.review
        except Review.DoesNotExist:
            return None
        request = self.context.get("request")
        return {
            "review_id": str(review.pk),
            "reviewer_id": str(review.reviewer_id),
            "reviewer_name": review.reviewer.full_name,
            "status": review.status,
            "reserved_at": review.assigned_at,
            "is_mine": bool(request and request.user.pk == review.reviewer_id),
        }


class ReviewDetailSerializer(ReviewListSerializer):
    call = CallEventSerializer(read_only=True)
    workflow_events = ReviewWorkflowEventSerializer(many=True, read_only=True)

    class Meta(ReviewListSerializer.Meta):
        fields = ReviewListSerializer.Meta.fields + ("call", "workflow_events")
