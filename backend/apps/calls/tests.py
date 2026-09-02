import secrets
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.tenancy.models import Branch, Company, Dialer

from .models import CallEvent


@override_settings(DIALER_CREDENTIAL_KEY=Fernet.generate_key().decode())
class WebhookTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Acme", slug="acme")
        self.branch = Branch.objects.create(company=company, name="Karachi", code="khi")
        self.secret = secrets.token_urlsafe(32)
        self.dialer = Dialer(
            branch=self.branch,
            name="Primary",
            api_url="https://dialer.example.com/non_agent_api.php",
            api_username="api",
        )
        self.dialer.set_api_password("secret")
        self.dialer.set_webhook_secret(self.secret)
        self.dialer.save()
        self.url = reverse(
            "vicidial-webhook",
            kwargs={"dialer_id": self.dialer.pk, "event_type": "dispo"},
        )

    def test_rejects_invalid_secret(self):
        response = self.client.get(self.url, {"token": "wrong", "lead_id": "12"})
        self.assertEqual(response.status_code, 403)

    def test_call_library_is_strictly_branch_scoped(self):
        user = User.objects.create_user(
            email="qa@example.com",
            password="a-very-strong-password",
            first_name="Amina",
            last_name="Khan",
            role=User.Role.QA,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        own = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="a" * 64,
            event_type=CallEvent.EventType.DISPOSITION,
            call_id="VISIBLE",
        )
        other_branch = Branch.objects.create(
            company=self.branch.company, name="Lahore", code="lhe"
        )
        other_dialer = Dialer(
            branch=other_branch,
            name="Secondary",
            api_url="https://secondary.example.com/non_agent_api.php",
            api_username="api",
        )
        other_dialer.set_api_password("secret")
        other_dialer.set_webhook_secret("another-long-webhook-secret")
        other_dialer.save()
        CallEvent.objects.create(
            dialer=other_dialer,
            branch=other_branch,
            event_key="b" * 64,
            event_type=CallEvent.EventType.DISPOSITION,
            call_id="HIDDEN",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("call-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [str(own.pk)])

    @patch("apps.calls.webhooks.announce_call")
    @patch("apps.calls.webhooks.resolve_recording.delay")
    def test_ingestion_is_idempotent_and_branch_scoped(self, queue_task, announce):
        payload = {
            "token": self.secret,
            "lead_id": "123",
            "call_id": "CALL-1",
            "uniqueid": "U-1",
            "dispo": "SALE",
            "talk_time": "42",
            "user": "agent01",
        }
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.get(self.url, payload)
            second = self.client.get(self.url, payload)
        self.assertTrue(first.json()["created"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(CallEvent.objects.count(), 1)
        self.assertEqual(CallEvent.objects.get().branch, self.branch)
        queue_task.assert_called_once()
        announce.assert_called_once()
