import secrets
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.tenancy.models import Branch, Company, Dialer
from config.celery import app as celery_app

from .models import CallEvent
from .services import download_recording, lookup_recording, parse_recordings
from .tasks import fetch_recording, resolve_recording


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
            lead_id="LEAD-123",
            phone_number="+923001234567",
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
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual([row["id"] for row in payload["results"]], [str(own.pk)])
        self.assertEqual(payload["results"][0]["lead_id"], "LEAD-123")
        self.assertEqual(payload["results"][0]["phone_number"], "+923001234567")

    def test_call_library_uses_server_side_pagination(self):
        user = User.objects.create_superuser(
            email="admin@example.com",
            password="a-very-strong-password",
            first_name="System",
            last_name="Administrator",
            must_change_password=False,
        )
        CallEvent.objects.bulk_create(
            [
                CallEvent(
                    dialer=self.dialer,
                    branch=self.branch,
                    event_key=f"{index:064d}",
                    event_type=CallEvent.EventType.DISPOSITION,
                    call_id=f"CALL-{index}",
                )
                for index in range(25)
            ]
        )
        self.client.force_login(user)

        first_page = self.client.get(
            reverse("call-list"), {"page": 1, "page_size": 10}
        ).json()
        last_page = self.client.get(
            reverse("call-list"), {"page": 3, "page_size": 10}
        ).json()

        self.assertEqual(first_page["count"], 25)
        self.assertEqual(len(first_page["results"]), 10)
        self.assertIsNotNone(first_page["next"])
        self.assertEqual(len(last_page["results"]), 5)
        self.assertIsNone(last_page["next"])

    def test_call_library_combines_search_dimensions_ranges_and_ordering(self):
        user = User.objects.create_user(
            email="filters@example.com",
            password="a-very-strong-password",
            first_name="Filter",
            last_name="Tester",
            role=User.Role.QA,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        now = timezone.now()
        matching = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="filter-match".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            call_id="SEARCH-ME",
            lead_id="LEAD-900",
            agent_user="agent-1",
            campaign="retention",
            phone_number="+923001112233",
            disposition="SALE",
            talk_time=95,
            call_date=now - timedelta(hours=1),
            recording_download_status=CallEvent.Status.DOWNLOADED,
        )
        CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="filter-miss".ljust(64, "0"),
            event_type=CallEvent.EventType.NO_AGENT,
            call_id="OTHER",
            agent_user="agent-2",
            campaign="support",
            disposition="DROP",
            talk_time=15,
            call_date=now - timedelta(days=2),
            recording_download_status=CallEvent.Status.FAILED,
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse("call-list"),
            {
                "search": "1112233",
                "agent": ["agent-1", "agent-3"],
                "campaign": "retention",
                "disposition": "SALE",
                "dialer": self.dialer.name,
                "event_type": CallEvent.EventType.DISPOSITION,
                "recording_status": CallEvent.Status.DOWNLOADED,
                "date_field": "call_date",
                "date_from": (now - timedelta(hours=2)).isoformat(),
                "date_to": now.isoformat(),
                "talk_time_min": "60",
                "talk_time_max": "120",
                "ordering": "-talk_time",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(matching.pk))

    def test_call_library_rejects_invalid_filter_inputs(self):
        user = User.objects.create_superuser(
            email="filter-admin@example.com",
            password="a-very-strong-password",
            first_name="Filter",
            last_name="Administrator",
            must_change_password=False,
        )
        self.client.force_login(user)
        url = reverse("call-list")
        now = timezone.now()
        invalid_queries = [
            {"recording_status": "unknown"},
            {"event_type": "unknown"},
            {"date_field": "deleted_at"},
            {"date_from": "not-a-date"},
            {"date_from": now.isoformat(), "date_to": (now - timedelta(days=1)).isoformat()},
            {"talk_time_min": "-1"},
            {"talk_time_min": "100", "talk_time_max": "10"},
            {"ordering": "raw_payload"},
            {"agent": [f"agent-{index}" for index in range(51)]},
        ]
        for query in invalid_queries:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(url, query).status_code, 400)

    def test_filter_options_are_branch_scoped_and_ignore_blanks(self):
        user = User.objects.create_user(
            email="options@example.com",
            password="a-very-strong-password",
            first_name="Option",
            last_name="Tester",
            role=User.Role.QA,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="option-visible".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            agent_user="visible-agent",
            campaign="visible-campaign",
            disposition="SALE",
        )
        other_branch = Branch.objects.create(
            company=self.branch.company, name="Islamabad", code="isb"
        )
        other_dialer = Dialer(
            branch=other_branch,
            name="Hidden dialer",
            api_url="https://hidden.example.com/non_agent_api.php",
            api_username="api",
        )
        other_dialer.set_api_password("secret")
        other_dialer.set_webhook_secret("hidden-webhook-secret-value")
        other_dialer.save()
        CallEvent.objects.create(
            dialer=other_dialer,
            branch=other_branch,
            event_key="option-hidden".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            agent_user="hidden-agent",
            campaign="hidden-campaign",
            disposition="HIDDEN",
        )
        self.client.force_login(user)
        payload = self.client.get(reverse("call-filter-options")).json()
        self.assertEqual(payload["agents"], ["visible-agent"])
        self.assertEqual(payload["campaigns"], ["visible-campaign"])
        self.assertEqual(payload["dispositions"], ["SALE"])
        self.assertEqual(payload["dialers"], [self.dialer.name])

    def test_recording_endpoint_supports_byte_ranges_and_downloads(self):
        user = User.objects.create_superuser(
            email="recordings@example.com",
            password="a-very-strong-password",
            first_name="System",
            last_name="Administrator",
            must_change_password=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            recording_path = Path(directory) / "sample.mp3"
            recording_path.write_bytes(b"0123456789")
            event = CallEvent.objects.create(
                dialer=self.dialer,
                branch=self.branch,
                event_key="recording".ljust(64, "0"),
                event_type=CallEvent.EventType.DISPOSITION,
                call_id="CALL-AUDIO",
                recording_path=str(recording_path),
                recording_download_status=CallEvent.Status.DOWNLOADED,
            )
            self.client.force_login(user)
            url = reverse("call-recording", kwargs={"pk": event.pk})

            partial = self.client.get(url, HTTP_RANGE="bytes=2-5")
            self.assertEqual(partial.status_code, 206)
            self.assertEqual(partial["Accept-Ranges"], "bytes")
            self.assertEqual(partial["Content-Range"], "bytes 2-5/10")
            self.assertEqual(partial["Content-Length"], "4")
            self.assertEqual(b"".join(partial.streaming_content), b"2345")

            download = self.client.get(url, {"download": "1"})
            self.assertEqual(download.status_code, 200)
            self.assertIn("attachment", download["Content-Disposition"])

            invalid = self.client.get(url, HTTP_RANGE="bytes=20-30")
            self.assertEqual(invalid.status_code, 416)
            self.assertEqual(invalid["Content-Range"], "bytes */10")

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


class RecordingTaskConfigurationTests(TestCase):
    def test_recording_tasks_route_to_the_recordings_queue(self):
        for task in (resolve_recording, fetch_recording):
            route = celery_app.amqp.router.route(
                {}, task.name, args=(), kwargs={}
            )
            self.assertEqual(route["queue"].name, "recordings")

    def test_recording_tasks_are_rate_limited(self):
        self.assertEqual(resolve_recording.rate_limit, "2/s")
        self.assertEqual(fetch_recording.rate_limit, "1/s")


class RecordingResponseParsingTests(SimpleTestCase):
    def test_rows_without_a_recording_location_are_ignored(self):
        response = "2026-09-04 01:02:03|agent01|42|123|30|"

        self.assertEqual(parse_recordings(response), [])

    @override_settings(RECORDING_DOWNLOAD_VERIFY_TLS=False)
    @patch("apps.calls.services.validate_recording_url")
    @patch("apps.calls.services.httpx.Client", side_effect=RuntimeError("stop"))
    def test_tls_verification_is_disabled_only_for_downloads(
        self, client_factory, _validate_url
    ):
        dialer = SimpleNamespace(request_timeout_seconds=15)

        with self.assertRaisesRegex(RuntimeError, "stop"):
            download_recording(
                dialer, "https://203.0.113.1/recording.mp3", uuid.uuid4()
            )

        self.assertFalse(client_factory.call_args.kwargs["verify"])

    @patch("apps.calls.services.httpx.Client", side_effect=RuntimeError("stop"))
    def test_dialer_api_lookup_keeps_tls_verification_enabled(self, client_factory):
        dialer = SimpleNamespace(
            api_source="qa_portal",
            api_username="api",
            api_url="https://dialer.example.com/non_agent_api.php",
            request_timeout_seconds=15,
            get_api_password=lambda: "secret",
        )
        event = SimpleNamespace(call_date=None, lead_id="123")

        with self.assertRaisesRegex(RuntimeError, "stop"):
            lookup_recording(dialer, event)

        self.assertTrue(client_factory.call_args.kwargs["verify"])
