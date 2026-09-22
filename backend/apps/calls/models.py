import uuid

from django.db import models


class CallEvent(models.Model):
    class EventType(models.TextChoices):
        DISPOSITION = "dispo", "Disposition"
        NO_AGENT = "no_agent", "No agent"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RETRYING = "retrying", "Retrying"
        FOUND = "found", "Found"
        DOWNLOADING = "downloading", "Downloading"
        DOWNLOADED = "downloaded", "Downloaded"
        NOT_FOUND = "not_found", "Not found"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    class Direction(models.TextChoices):
        INBOUND = "INBOUND", "Inbound"
        TRANSFER = "TRANSFER", "Transfer"
        CLOSER = "CLOSER", "Closer"
        OUTBOUND = "OUTBOUND", "Outbound"

    class DialMethod(models.TextChoices):
        AUTO = "AUTO", "Auto Dial"
        MANUAL = "MANUAL", "Manual Dial"
        UNKNOWN = "UNKNOWN", "Unknown"
        NOT_APPLICABLE = "N/A", "Not Applicable"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    dialer = models.ForeignKey(
        "tenancy.Dialer",
        on_delete=models.PROTECT,
        related_name="call_events",
    )

    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.PROTECT,
        related_name="call_events",
    )

    event_key = models.CharField(
        max_length=64,
    )

    event_type = models.CharField(
        max_length=20,
        choices=EventType.choices,
    )

    received_at = models.DateTimeField(
        auto_now_add=True,
    )

    # ---------------------------------------------------------
    # VICIdial identifiers
    # ---------------------------------------------------------

    call_id = models.CharField(
        max_length=160,
        blank=True,
        db_index=True,
    )

    close_call_id = models.CharField(
        max_length=160,
        blank=True,
    )

    xfer_call_id = models.CharField(
        max_length=160,
        blank=True,
    )

    unique_id = models.CharField(
        max_length=160,
        blank=True,
        db_index=True,
    )

    lead_id = models.CharField(
        max_length=80,
        blank=True,
        db_index=True,
    )

    agent_log_id = models.CharField(
        max_length=80,
        blank=True,
    )

    # ---------------------------------------------------------
    # Agent / Team
    # ---------------------------------------------------------

    agent_user = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
    )

    agent_name = models.CharField(
        max_length=160,
        blank=True,
        db_index=True,
    )

    team_name = models.CharField(
        max_length=160,
        blank=True,
        db_index=True,
    )

    team = models.ForeignKey(
        "tenancy.Team",
        on_delete=models.PROTECT,
        related_name="call_events",
        null=True,
        blank=True,
    )

    # ---------------------------------------------------------
    # Campaign / Inbound group
    # ---------------------------------------------------------

    campaign = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
    )

    closer_group = models.CharField(
        max_length=120,
        blank=True,
    )

    did_id = models.CharField(
        max_length=80,
        blank=True,
    )

    did_pattern = models.CharField(
        max_length=160,
        blank=True,
    )

    # ---------------------------------------------------------
    # Call classification
    # ---------------------------------------------------------

    call_direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        default=Direction.OUTBOUND,
        db_index=True,
    )

    dial_method = models.CharField(
        max_length=16,
        choices=DialMethod.choices,
        default=DialMethod.UNKNOWN,
        db_index=True,
    )

    # ---------------------------------------------------------
    # Lead / call information
    # ---------------------------------------------------------

    phone_number = models.CharField(
        max_length=40,
        blank=True,
    )

    list_id = models.CharField(
        max_length=80,
        blank=True,
    )

    disposition = models.CharField(
        max_length=40,
        blank=True,
        db_index=True,
    )

    talk_time = models.PositiveIntegerField(
        default=0,
    )

    termination_reason = models.CharField(
        max_length=160,
        blank=True,
    )

    call_date = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    # ---------------------------------------------------------
    # Recording information
    # ---------------------------------------------------------

    source_recording_id = models.CharField(
        max_length=160,
        blank=True,
    )

    source_recording_filename = models.CharField(
        max_length=255,
        blank=True,
    )

    recording_source_url = models.URLField(
        max_length=1000,
        blank=True,
    )

    recording_uuid = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
    )

    recording_path = models.CharField(
        max_length=1000,
        blank=True,
    )

    recording_size_bytes = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )

    recording_sha256 = models.CharField(
        max_length=64,
        blank=True,
    )

    # ---------------------------------------------------------
    # Recording lookup state
    # ---------------------------------------------------------

    recording_lookup_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    recording_lookup_attempts = models.PositiveSmallIntegerField(
        default=0,
    )

    recording_lookup_last_error = models.TextField(
        blank=True,
    )

    # ---------------------------------------------------------
    # Recording download state
    # ---------------------------------------------------------

    recording_download_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    recording_download_attempts = models.PositiveSmallIntegerField(
        default=0,
    )

    recording_download_last_error = models.TextField(
        blank=True,
    )

    # ---------------------------------------------------------
    # Original VICIdial payload
    # ---------------------------------------------------------

    raw_payload = models.JSONField(
        default=dict,
    )

    class Meta:
        ordering = [
            "-received_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "dialer",
                    "event_key",
                ],
                name="unique_event_per_dialer",
            )
        ]

        indexes = [
            models.Index(
                fields=[
                    "branch",
                    "-received_at",
                ]
            ),
            models.Index(
                fields=[
                    "branch",
                    "recording_download_status",
                ]
            ),
            models.Index(
                fields=[
                    "branch",
                    "campaign",
                    "-received_at",
                ]
            ),
        ]

    def __str__(self) -> str:
        return self.call_id or self.lead_id or str(self.id)


class Review(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        REVISION_REQUIRED = "revision_required", "Revision required"
        COMPLETED = "completed", "Completed"
        DISPUTED = "disputed", "Disputed"

    class Rating(models.TextChoices):
        NOT_EVALUABLE = "not_evaluable", "Not Evaluable"
        EXCELLENT = "excellent", "Excellent"
        VERY_GOOD = "very_good", "Very Good"
        GOOD = "good", "Good"
        NEEDS_IMPROVEMENT = "needs_improvement", "Needs Improvement"
        UNSATISFACTORY = "unsatisfactory", "Unsatisfactory"
        AUTOMATIC_FAIL = "automatic_fail", "Automatic Fail"

    class Outcome(models.TextChoices):
        NOT_EVALUABLE = "not_evaluable", "Not Evaluable"
        EXCEEDS_EXPECTATIONS = "exceeds_expectations", "Exceeds Expectations"
        MEETS_EXPECTATIONS = "meets_expectations", "Meets Expectations"
        MEETS_MINIMUM_STANDARD = "meets_minimum_standard", "Meets Minimum Standard"
        COACHING_REQUIRED = "coaching_required", "Coaching Required"
        PERFORMANCE_ACTION_REQUIRED = (
            "performance_action_required",
            "Performance Action Required",
        )
        IMMEDIATE_ESCALATION = "immediate_escalation", "Immediate Escalation"

    class EmailStatus(models.TextChoices):
        DISABLED = "disabled", "Disabled"
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    class LeaderStatus(models.TextChoices):
        PENDING = "pending", "Needs review"
        ACKNOWLEDGED = "acknowledged", "Reviewed"
        COACHING_PLANNED = "coaching_planned", "Coaching planned"
        COACHING_COMPLETED = "coaching_completed", "Coaching completed"
        ESCALATED = "escalated", "Escalated"
        RETURNED_TO_QA = "returned_to_qa", "Returned to QA"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    call = models.OneToOneField(
        CallEvent,
        on_delete=models.PROTECT,
        related_name="review",
    )

    reviewer = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="reviews",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ASSIGNED,
    )

    score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class EvaluationType(models.TextChoices):
        FULL = "full", "Full call"
        PARTIAL = "partial", "Partial call"
        NOT_EVALUABLE = "not_evaluable", "Not evaluable"
        AGENT_PREMATURE = "agent_premature", "Agent ended early"

    class CoverageTier(models.TextChoices):
        INSUFFICIENT = "insufficient", "Insufficient interaction"
        LIMITED = "limited", "Limited coverage"
        PARTIAL = "partial", "Partial coverage"
        FULL = "full", "Full coverage"

    evaluation_type = models.CharField(
        max_length=24,
        choices=EvaluationType.choices,
        default=EvaluationType.FULL,
    )
    evaluation_reason = models.CharField(max_length=40, blank=True)
    category_applicability = models.JSONField(default=dict, blank=True)
    category_applicability_reasons = models.JSONField(default=dict, blank=True)
    criterion_applicability = models.JSONField(default=dict, blank=True)
    earned_points = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    applicable_points = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    coverage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    coverage_tier = models.CharField(
        max_length=20,
        choices=CoverageTier.choices,
        blank=True,
    )

    scorecard_version = models.CharField(max_length=40, blank=True)
    scorecard_snapshot = models.JSONField(default=dict, blank=True)
    scores = models.JSONField(default=dict, blank=True)
    criterion_evidence = models.JSONField(default=dict, blank=True)
    critical_errors = models.JSONField(default=list, blank=True)
    critical_error_evidence = models.JSONField(default=dict, blank=True)
    rating = models.CharField(max_length=32, choices=Rating.choices, blank=True)
    outcome = models.CharField(max_length=40, choices=Outcome.choices, blank=True)
    feedback_summary = models.TextField(blank=True)
    strengths = models.TextField(blank=True)
    improvement_areas = models.TextField(blank=True)
    expected_behavior = models.TextField(blank=True)
    coaching_plan = models.TextField(blank=True)
    team_leader = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="qa_reports_received",
        null=True,
        blank=True,
    )
    email_status = models.CharField(
        max_length=16,
        choices=EmailStatus.choices,
        default=EmailStatus.DISABLED,
    )
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_last_error = models.TextField(blank=True)
    leader_status = models.CharField(
        max_length=24,
        choices=LeaderStatus.choices,
        default=LeaderStatus.PENDING,
    )
    coaching_due_at = models.DateTimeField(null=True, blank=True)
    leader_reviewed_at = models.DateTimeField(null=True, blank=True)
    leader_closed_at = models.DateTimeField(null=True, blank=True)
    leader_updated_at = models.DateTimeField(null=True, blank=True)
    revision_requested_at = models.DateTimeField(null=True, blank=True)
    revision_reason = models.TextField(blank=True)
    revision_count = models.PositiveIntegerField(default=0)

    assigned_at = models.DateTimeField(
        auto_now_add=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "-assigned_at",
        ]
        indexes = [
            models.Index(
                fields=["reviewer", "status", "-assigned_at"],
                name="review_owner_status_idx",
            ),
            models.Index(
                fields=["team_leader", "status", "-completed_at"],
                name="review_leader_status_idx",
            ),
            models.Index(
                fields=["team_leader", "leader_status", "-completed_at"],
                name="review_leader_work_idx",
            ),
        ]


class ReviewWorkflowEvent(models.Model):
    class EventType(models.TextChoices):
        STATUS_CHANGED = "status_changed", "Status changed"
        NOTE_ADDED = "note_added", "Note added"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(
        Review,
        on_delete=models.CASCADE,
        related_name="workflow_events",
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="review_workflow_events",
    )
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    note = models.TextField(blank=True)
    coaching_due_at = models.DateTimeField(null=True, blank=True)
    email_status = models.CharField(
        max_length=16,
        choices=Review.EmailStatus.choices,
        default=Review.EmailStatus.DISABLED,
    )
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["review", "-created_at"],
                name="review_workflow_event_idx",
            )
        ]


class AnalysisPresence(models.Model):
    """Short-lived viewer presence for an open QA analysis workspace."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(
        CallEvent,
        on_delete=models.CASCADE,
        related_name="analysis_presence",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="analysis_presence",
    )
    channel_name = models.CharField(max_length=255, unique=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["call", "last_seen_at"])]
