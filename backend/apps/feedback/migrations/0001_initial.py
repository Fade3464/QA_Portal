# Generated for QA Portal feedback support.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Feedback",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("message", models.TextField()),
                ("status", models.CharField(choices=[("open", "Open"), ("reviewed", "Reviewed")], default="open", max_length=16)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_feedback", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="feedback_submissions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="FeedbackImage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("image", models.ImageField(upload_to="feedback-images/%Y/%m/")),
                ("original_name", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("feedback", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="images", to="feedback.feedback")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddIndex(
            model_name="feedback",
            index=models.Index(fields=["status", "-created_at"], name="feedback_status_created_idx"),
        ),
    ]
