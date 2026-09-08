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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dialer = models.ForeignKey(
        "tenancy.Dialer", on_delete=models.PROTECT, related_name="call_events"
    )
    branch = models.ForeignKey(
        "tenancy.Branch", on_delete=models.PROTECT, related_name="call_events"
    )
    event_key = models.CharField(max_length=64)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    received_at = models.DateTimeField(auto_now_add=True)
    call_id = models.CharField(max_length=160, blank=True, db_index=True)
    close_call_id = models.CharField(max_length=160, blank=True)
    xfer_call_id = models.CharField(max_length=160, blank=True)
    unique_id = models.CharField(max_length=160, blank=True, db_index=True)
    lead_id = models.CharField(max_length=80, blank=True, db_index=True)
    agent_log_id = models.CharField(max_length=80, blank=True)
    agent_user = models.CharField(max_length=120, blank=True, db_index=True)
    agent_name = models.CharField(max_length=160, blank=True, db_index=True)
    team_name = models.CharField(max_length=160, blank=True, db_index=True)
    team = models.ForeignKey(
        "tenancy.Team",
        on_delete=models.PROTECT,
        related_name="call_events",
        null=True,
        blank=True,
    )
    campaign = models.CharField(max_length=120, blank=True, db_index=True)
    closer_group = models.CharField(max_length=120, blank=True)
    did_id = models.CharField(max_length=80, blank=True)
    did_pattern = models.CharField(max_length=160, blank=True)
    call_direction = models.CharField(
        max_length=10,
        choices=Direction.choices,
        default=Direction.OUTBOUND,
        db_index=True,
    )
    phone_number = models.CharField(max_length=40, blank=True)
    list_id = models.CharField(max_length=80, blank=True)
    disposition = models.CharField(max_length=40, blank=True, db_index=True)
    talk_time = models.PositiveIntegerField(default=0)
    termination_reason = models.CharField(max_length=160, blank=True)
    call_date = models.DateTimeField(null=True, blank=True, db_index=True)
    source_recording_id = models.CharField(max_length=160, blank=True)
    source_recording_filename = models.CharField(max_length=255, blank=True)
    recording_source_url = models.URLField(max_length=1000, blank=True)
    recording_uuid = models.UUIDField(null=True, blank=True, unique=True)
    recording_path = models.CharField(max_length=1000, blank=True)
    recording_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    recording_sha256 = models.CharField(max_length=64, blank=True)
    recording_lookup_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    recording_lookup_attempts = models.PositiveSmallIntegerField(default=0)
    recording_lookup_last_error = models.TextField(blank=True)
    recording_download_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    recording_download_attempts = models.PositiveSmallIntegerField(default=0)
    recording_download_last_error = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict)

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dialer", "event_key"], name="unique_event_per_dialer"
            )
        ]
        indexes = [
            models.Index(fields=["branch", "-received_at"]),
            models.Index(fields=["branch", "recording_download_status"]),
            models.Index(fields=["branch", "campaign", "-received_at"]),
        ]

    def __str__(self) -> str:
        return self.call_id or self.lead_id or str(self.id)


class Review(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        DISPUTED = "disputed", "Disputed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.OneToOneField(
        CallEvent, on_delete=models.PROTECT, related_name="review"
    )
    reviewer = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="reviews"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ASSIGNED
    )
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-assigned_at"]
