import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.models import User

from .models import Feedback


class FeedbackApiTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.user = User.objects.create_user(
            email="user@example.com",
            password="StrongPassword123!",
            first_name="Portal",
            last_name="User",
            role=User.Role.QA,
        )
        self.other = User.objects.create_user(
            email="other@example.com",
            password="StrongPassword123!",
            first_name="Other",
            last_name="User",
            role=User.Role.QA,
        )
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="StrongPassword123!",
            first_name="System",
            last_name="Administrator",
        )

    def tearDown(self):
        self.override.disable()
        self.media.cleanup()

    @staticmethod
    def _image(name="screen.png"):
        source = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(source, format="PNG")
        return SimpleUploadedFile(name, source.getvalue(), "image/png")

    def test_authenticated_user_can_submit_feedback_with_images(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("feedback-submit"),
            {"message": "The report filter is difficult to use.", "images": [self._image()]},
        )
        self.assertEqual(response.status_code, 201, response.content)
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.user, self.user)
        self.assertEqual(feedback.images.count(), 1)
        self.assertTrue(feedback.images.first().image.name.endswith(".webp"))

    def test_only_system_administrator_can_review_feedback(self):
        feedback = Feedback.objects.create(user=self.user, message="Please review this.")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("feedback-admin-list")).status_code, 403)
        self.assertEqual(
            self.client.patch(
                reverse("feedback-admin-detail", kwargs={"pk": feedback.pk}),
                {"reviewed": True},
                content_type="application/json",
            ).status_code,
            403,
        )

        self.client.force_login(self.admin)
        listing = self.client.get(reverse("feedback-admin-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["results"][0]["id"], str(feedback.pk))
        reviewed = self.client.patch(
            reverse("feedback-admin-detail", kwargs={"pk": feedback.pk}),
            {"reviewed": True},
            content_type="application/json",
        )
        self.assertEqual(reviewed.status_code, 200, reviewed.content)
        feedback.refresh_from_db()
        self.assertEqual(feedback.status, Feedback.Status.REVIEWED)
        self.assertEqual(feedback.reviewed_by, self.admin)
        self.assertIsNotNone(feedback.reviewed_at)

    def test_feedback_image_is_private_to_owner_and_system_administrator(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("feedback-submit"),
            {"message": "Screenshot attached.", "images": [self._image()]},
        )
        feedback = Feedback.objects.get(pk=response.json()["id"])
        image = feedback.images.get()
        url = reverse("feedback-image", kwargs={"feedback_id": feedback.pk, "image_id": image.pk})
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
