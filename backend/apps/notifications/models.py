import uuid

from django.conf import settings
from django.db import models


class SystemNotification(models.Model):
    class Category(models.TextChoices):
        UNKNOWN_TEAM = "unknown_team", "Unknown team"
        QA_REPORT_READY = "qa_report_ready", "QA report ready"
        QA_REPORT_RETURNED = "qa_report_returned", "QA report returned"

    class Severity(models.TextChoices):
        INFO = "info", "Information"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=40, choices=Category.choices)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.INFO
    )
    dedupe_key = models.CharField(max_length=160, unique=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.PROTECT,
        related_name="system_notifications",
        null=True,
        blank=True,
    )
    call = models.ForeignKey(
        "calls.CallEvent",
        on_delete=models.SET_NULL,
        related_name="system_notifications",
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    occurrences = models.PositiveIntegerField(default=1)
    read_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="read_system_notifications", blank=True
    )
    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="system_notifications",
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(
                fields=["resolved_at", "-updated_at"],
                name="notificatio_resolve_8fe72b_idx",
            ),
            models.Index(
                fields=["category", "-updated_at"],
                name="notificatio_categor_e9455d_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.title
