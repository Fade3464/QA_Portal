import uuid

from django.conf import settings
from django.db import models


class Feedback(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWED = "reviewed", "Reviewed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="feedback_submissions",
    )
    message = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_feedback",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="feedback_status_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Feedback from {self.user} at {self.created_at:%Y-%m-%d %H:%M}"


class FeedbackImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feedback = models.ForeignKey(
        Feedback, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to="feedback-images/%Y/%m/")
    original_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.original_name or str(self.pk)
