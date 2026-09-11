import secrets
import tempfile
import uuid
import wave
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import SystemNotification
from apps.tenancy.models import (
    Branch,
    Company,
    Dialer,
    DialerCampaign,
    QAProjectAssignment,
    Team,
)
from config.celery import app as celery_app

from .models import CallEvent, Review
from .serializers import CallEventSerializer
from .services import (
    RecordingResult,
    download_recording,
    lookup_recording,
    parse_recordings,
    recording_duration_seconds,
    validate_recording_url,
)
from .tasks import fetch_recording, resolve_recording
from .webhooks import infer_call_direction, infer_dial_method


class CallClassificationTests(SimpleTestCase):
    def test_dial_method_inference(self):
        cases = (
            (("M123456", CallEvent.Direction.OUTBOUND), CallEvent.DialMethod.MANUAL),
            ((" m123456 ", CallEvent.Direction.OUTBOUND), CallEvent.DialMethod.MANUAL),
            (("V123456", CallEvent.Direction.OUTBOUND), CallEvent.DialMethod.AUTO),
            ((" v123456 ", CallEvent.Direction.OUTBOUND), CallEvent.DialMethod.AUTO),
            (("", CallEvent.Direction.OUTBOUND), CallEvent.DialMethod.UNKNOWN),
            ((None, CallEvent.Direction.OUTBOUND), CallEvent.DialMethod.UNKNOWN),
            (("CUSTOM-1", CallEvent.Direction.OUTBOUND), CallEvent.DialMethod.UNKNOWN),
            (
                ("M123456", CallEvent.Direction.INBOUND),
                CallEvent.DialMethod.NOT_APPLICABLE,
            ),
            (
                ("M123456", CallEvent.Direction.TRANSFER),
                CallEvent.DialMethod.NOT_APPLICABLE,
            ),
            (
                ("V123456", CallEvent.Direction.CLOSER),
                CallEvent.DialMethod.NOT_APPLICABLE,
            ),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(infer_dial_method(*arguments), expected)


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

    def test_call_library_is_strictly_qa_project_scoped(self):
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
        allowed_project = DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="ALLOWED",
            project_name="Allowed Project",
        )
        QAProjectAssignment.objects.create(qa=user, dialer_campaign=allowed_project)
        own = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="a" * 64,
            event_type=CallEvent.EventType.DISPOSITION,
            call_id="VISIBLE",
            lead_id="LEAD-123",
            phone_number="+923001234567",
            campaign="allowed",
            termination_reason="AGENT",
        )
        CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="same-branch-hidden".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            call_id="SAME-BRANCH-HIDDEN",
            campaign="UNASSIGNED",
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
        self.assertEqual(payload["results"][0]["termination_reason"], "AGENT")
        self.assertEqual(payload["results"][0]["call_direction"], "OUTBOUND")

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

    def test_column_sorting_is_applied_before_pagination(self):
        user = User.objects.create_superuser(
            email="sorting@example.com",
            password="a-very-strong-password",
            first_name="System",
            last_name="Administrator",
            must_change_password=False,
        )
        self.client.force_login(user)
        for index in range(12):
            CallEvent.objects.create(
                dialer=self.dialer,
                branch=self.branch,
                event_key=f"sort-{index}",
                event_type=CallEvent.EventType.DISPOSITION,
                campaign="Included",
                lead_id=f"{index:04d}",
                phone_number=f"555{index:04d}",
                agent_name=f"Agent {index:02d}",
                team_name=f"Team {index:02d}",
                disposition=f"D{index:02d}",
                talk_time=index,
            )
        for field in (
            "lead_id",
            "phone_number",
            "agent_name",
            "team_name",
            "campaign",
            "disposition",
            "talk_time",
            "received_at",
        ):
            for prefix in ("", "-"):
                ordering = f"{prefix}{field}"
                with self.subTest(ordering=ordering):
                    expected = list(
                        CallEvent.objects.order_by(ordering, "-id").values_list(
                            "id", flat=True
                        )
                    )
                    pages = []
                    for page in (1, 2):
                        response = self.client.get(
                            reverse("call-list"),
                            {
                                "ordering": ordering,
                                "page": page,
                                "page_size": 10,
                                "campaign": "Included",
                            },
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["count"], 12)
                        pages.extend(row["id"] for row in response.json()["results"])
                    self.assertEqual(pages, [str(pk) for pk in expected])

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
        project = DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="RETENTION",
            project_name="Customer Retention",
        )
        QAProjectAssignment.objects.create(qa=user, dialer_campaign=project)
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
            termination_reason="AGENT",
            dial_method=CallEvent.DialMethod.MANUAL,
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
                "project": "customer retention",
                "disposition": "SALE",
                "termination_reason": "agent",
                "dialer": self.dialer.name,
                "event_type": CallEvent.EventType.DISPOSITION,
                "dial_method": CallEvent.DialMethod.MANUAL,
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
        self.assertEqual(
            response.json()["results"][0]["project_name"], "Customer Retention"
        )

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
            {"dial_method": "INVALID"},
            {"date_field": "deleted_at"},
            {"date_from": "not-a-date"},
            {
                "date_from": now.isoformat(),
                "date_to": (now - timedelta(days=1)).isoformat(),
            },
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
            termination_reason="Caller",
            dial_method=CallEvent.DialMethod.AUTO,
        )
        project = DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="visible-campaign",
            project_name="Visible Project",
        )
        QAProjectAssignment.objects.create(qa=user, dialer_campaign=project)
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
        DialerCampaign.objects.create(
            dialer=other_dialer,
            campaign="hidden-campaign",
            project_name="Hidden Project",
        )
        self.client.force_login(user)
        payload = self.client.get(reverse("call-filter-options")).json()
        self.assertEqual(payload["agents"], ["visible-agent"])
        self.assertEqual(payload["campaigns"], ["visible-campaign"])
        self.assertEqual(payload["projects"], ["Visible Project"])
        self.assertEqual(payload["dispositions"], ["SALE"])
        self.assertEqual(payload["termination_reasons"], ["Caller"])
        self.assertEqual(
            payload["dial_methods"],
            [
                {"value": "AUTO", "label": "Auto Dial"},
                {"value": "MANUAL", "label": "Manual Dial"},
                {"value": "UNKNOWN", "label": "Unknown"},
                {"value": "N/A", "label": "Not Applicable"},
            ],
        )
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
            "closecallid": "CLOSE-1",
            "xfercallid": "XFER-1",
            "uniqueid": "U-1",
            "dispo": "SALE",
            "talk_time": "42",
            "user": "agent01",
            "group": "SUPPORT",
            "did_id": "42",
            "did_pattern": "18005551212",
        }
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.get(self.url, payload)
            second = self.client.get(self.url, payload)
        self.assertTrue(first.json()["created"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(CallEvent.objects.count(), 1)
        event = CallEvent.objects.get()
        self.assertEqual(event.branch, self.branch)
        self.assertEqual(event.call_direction, CallEvent.Direction.INBOUND)
        self.assertEqual(event.close_call_id, "CLOSE-1")
        self.assertEqual(event.xfer_call_id, "XFER-1")
        self.assertEqual(event.closer_group, "SUPPORT")
        self.assertEqual(event.did_id, "42")
        self.assertEqual(event.did_pattern, "18005551212")
        self.assertEqual(event.dial_method, CallEvent.DialMethod.NOT_APPLICABLE)
        self.assertEqual(
            first.json()["dial_method"], CallEvent.DialMethod.NOT_APPLICABLE
        )
        queue_task.assert_called_once()
        announce.assert_called_once()

    @patch("apps.calls.webhooks.announce_call")
    @patch("apps.calls.webhooks.resolve_recording.delay")
    def test_manual_dial_is_persisted_and_returned(self, _queue_task, _announce):
        response = self.client.get(
            self.url,
            {
                "token": self.secret,
                "lead_id": "MANUAL-LEAD-1",
                "call_id": " m1700000000 ",
                "user": "agent01",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dial_method"], CallEvent.DialMethod.MANUAL)
        event = CallEvent.objects.get(lead_id="MANUAL-LEAD-1")
        self.assertEqual(event.dial_method, CallEvent.DialMethod.MANUAL)
        self.assertEqual(CallEventSerializer(event).data["dial_method"], "MANUAL")

    def test_call_direction_inference_uses_closer_transfer_and_did_evidence(self):
        cases = (
            ((" CLOSE-99 ", None, "42", None, "SUPPORT"), CallEvent.Direction.INBOUND),
            (
                ("CLOSE-99", "XFER-1", None, None, "SUPPORT"),
                CallEvent.Direction.TRANSFER,
            ),
            (("CLOSE-99", None, None, None, "SUPPORT"), CallEvent.Direction.CLOSER),
            (
                (None, "XFER-1", "42", "18005551212", "SUPPORT"),
                CallEvent.Direction.OUTBOUND,
            ),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(infer_call_direction(*arguments), expected)

        for empty in (None, "", " 0 ", "NULL", "null", "NONE", "none"):
            with self.subTest(empty=empty):
                self.assertEqual(
                    infer_call_direction(empty, empty, empty, empty, empty),
                    CallEvent.Direction.OUTBOUND,
                )

    @patch("apps.calls.webhooks.announce_call")
    @patch("apps.calls.webhooks.resolve_recording.delay")
    def test_agent_full_name_assigns_team_case_insensitively(
        self, _queue_task, _announce
    ):
        leader = User.objects.create_user(
            email="leader@example.com",
            password="a-very-strong-password",
            first_name="Team",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        team = Team.objects.create(
            branch=self.branch,
            name="Annihilators",
            avatar="shield",
            team_leader=leader,
        )

        response = self.client.get(
            self.url,
            {
                "token": self.secret,
                "lead_id": "TEAM-1",
                "call_id": "TEAM-CALL-1",
                "user": "8014",
                "agent_full_name": "aNNIHILATORS - Ali",
            },
        )

        self.assertEqual(response.status_code, 200)
        event = CallEvent.objects.get(lead_id="TEAM-1")
        self.assertEqual(event.agent_name, "Ali")
        self.assertEqual(event.team_name, "aNNIHILATORS")
        self.assertEqual(event.team, team)
        self.assertEqual(CallEventSerializer(event).data["team_avatar"], "shield")
        self.assertFalse(SystemNotification.objects.exists())

    @patch("apps.calls.webhooks.announce_call")
    @patch("apps.calls.webhooks.resolve_recording.delay")
    def test_agent_full_name_prefix_can_match_team_leader_name(
        self, _queue_task, _announce
    ):
        leader = User.objects.create_user(
            email="fatima@example.com",
            password="a-very-strong-password",
            first_name="Fatima",
            last_name="Noor",
            role=User.Role.TEAM_LEADER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        team = Team.objects.create(
            branch=self.branch, name="Falcons", team_leader=leader
        )

        self.client.get(
            self.url,
            {
                "token": self.secret,
                "lead_id": "LEADER-1",
                "call_id": "LEADER-CALL-1",
                "user": "8020",
                "agent_full_name": "fATIMA nOOR - Amna",
            },
        )

        event = CallEvent.objects.get(lead_id="LEADER-1")
        self.assertEqual(event.team, team)
        self.assertEqual(event.agent_name, "Amna")
        self.assertFalse(SystemNotification.objects.exists())

    @patch("apps.calls.webhooks.announce_call")
    @patch("apps.calls.webhooks.resolve_recording.delay")
    def test_ambiguous_team_leader_prefix_stays_queued(self, _queue_task, _announce):
        leader = User.objects.create_user(
            email="shared-leader@example.com",
            password="a-very-strong-password",
            first_name="Shared",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        Team.objects.create(branch=self.branch, name="Alpha", team_leader=leader)
        Team.objects.create(branch=self.branch, name="Beta", team_leader=leader)

        self.client.get(
            self.url,
            {
                "token": self.secret,
                "lead_id": "AMBIGUOUS-1",
                "call_id": "AMBIGUOUS-CALL-1",
                "agent_full_name": "Shared Leader - Zain",
            },
        )

        event = CallEvent.objects.get(lead_id="AMBIGUOUS-1")
        self.assertIsNone(event.team)
        self.assertEqual(SystemNotification.objects.count(), 1)

    @patch("apps.calls.webhooks.announce_call")
    @patch("apps.calls.webhooks.resolve_recording.delay")
    def test_unknown_team_calls_are_queued_and_notification_is_deduplicated(
        self, _queue_task, _announce
    ):
        for index, full_name in enumerate(
            ("Night Owls - Sana", "night owls — Hira"), start=1
        ):
            response = self.client.get(
                self.url,
                {
                    "token": self.secret,
                    "lead_id": f"UNKNOWN-{index}",
                    "call_id": f"UNKNOWN-CALL-{index}",
                    "user": f"80{index}",
                    "agent_full_name": full_name,
                },
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(CallEvent.objects.filter(team__isnull=True).count(), 2)
        self.assertEqual(
            list(
                CallEvent.objects.order_by("call_id").values_list(
                    "agent_name", flat=True
                )
            ),
            ["Sana", "Hira"],
        )
        notification = SystemNotification.objects.get()
        self.assertEqual(notification.occurrences, 2)
        self.assertEqual(notification.metadata["normalized_team_name"], "night owls")

    @patch("apps.calls.webhooks.announce_call")
    @patch("apps.calls.webhooks.resolve_recording.delay")
    def test_creating_team_assigns_waiting_calls_and_resolves_notification(
        self, _queue_task, _announce
    ):
        self.client.get(
            self.url,
            {
                "token": self.secret,
                "lead_id": "WAITING-1",
                "call_id": "WAITING-CALL-1",
                "agent_full_name": "Ayesha Lead - Ayesha",
            },
        )
        leader = User.objects.create_user(
            email="resolver@example.com",
            password="a-very-strong-password",
            first_name="Ayesha",
            last_name="Lead",
            role=User.Role.TEAM_LEADER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        administrator = User.objects.create_superuser(
            email="resolve-admin@example.com",
            password="a-very-strong-password",
            first_name="System",
            last_name="Administrator",
            must_change_password=False,
        )
        self.client.force_login(administrator)

        response = self.client.post(
            "/api/v1/administration/teams/",
            {
                "branch": str(self.branch.pk),
                "name": "resolvers",
                "avatar": "shield",
                "team_leader": str(leader.pk),
                "is_active": True,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["avatar"], "shield")
        event = CallEvent.objects.get(lead_id="WAITING-1")
        self.assertEqual(str(event.team_id), response.json()["id"])
        self.assertIsNotNone(SystemNotification.objects.get().resolved_at)


@override_settings(DIALER_CREDENTIAL_KEY=Fernet.generate_key().decode())
class AnalysisReservationTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Analysis", slug="analysis")
        self.branch = Branch.objects.create(
            company=company, name="Analysis branch", code="analysis"
        )
        self.dialer = Dialer(
            branch=self.branch,
            name="Analysis dialer",
            api_url="https://dialer.example.com/non_agent_api.php",
            api_username="api",
        )
        self.dialer.set_api_password("secret")
        self.dialer.set_webhook_secret("analysis-webhook-secret-long-enough")
        self.dialer.save()
        campaign = DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="ANALYSIS",
            project_name="Analysis Project",
        )
        self.qa_one = User.objects.create_user(
            email="qa-one@example.com",
            password="a-very-strong-password",
            first_name="Amina",
            last_name="Khan",
            role=User.Role.QA,
            company=company,
            branch=self.branch,
            must_change_password=False,
        )
        self.qa_two = User.objects.create_user(
            email="qa-two@example.com",
            password="a-very-strong-password",
            first_name="Bilal",
            last_name="Ahmed",
            role=User.Role.QA,
            company=company,
            branch=self.branch,
            must_change_password=False,
        )
        for qa in (self.qa_one, self.qa_two):
            QAProjectAssignment.objects.create(qa=qa, dialer_campaign=campaign)
        self.call = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="analysis-call".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="analysis",
            recording_download_status=CallEvent.Status.DOWNLOADED,
            recording_path="/recordings/analysis.wav",
        )

    def url(self, name):
        return reverse(name, kwargs={"pk": self.call.pk})

    def test_reservation_is_atomic_idempotent_and_owned_by_one_qa(self):
        self.client.force_login(self.qa_one)
        first = self.client.post(self.url("call-reserve"))
        repeated = self.client.post(self.url("call-reserve"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.json()["review_id"], repeated.json()["review_id"])
        self.assertTrue(first.json()["is_mine"])
        self.assertEqual(Review.objects.filter(call=self.call).count(), 1)

        self.client.force_login(self.qa_two)
        blocked = self.client.post(self.url("call-reserve"))
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("Amina Khan", str(blocked.json()))

    def test_owner_can_release_and_another_qa_can_then_reserve(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        released = self.client.post(self.url("call-release"))
        self.assertEqual(released.status_code, 204)
        self.assertFalse(Review.objects.filter(call=self.call).exists())

        self.client.force_login(self.qa_two)
        reserved = self.client.post(self.url("call-reserve"))
        self.assertEqual(reserved.status_code, 200)
        self.assertEqual(reserved.json()["reviewer_id"], str(self.qa_two.pk))

    def test_non_owner_cannot_release_reservation(self):
        Review.objects.create(
            call=self.call,
            reviewer=self.qa_one,
            status=Review.Status.IN_PROGRESS,
        )
        self.client.force_login(self.qa_two)
        response = self.client.post(self.url("call-release"))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Review.objects.filter(call=self.call).exists())

    def test_analysis_state_and_list_report_reservation_ownership(self):
        Review.objects.create(
            call=self.call,
            reviewer=self.qa_one,
            status=Review.Status.IN_PROGRESS,
        )
        self.client.force_login(self.qa_two)
        detail = self.client.get(self.url("call-analysis"))
        listing = self.client.get(reverse("call-list"))
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.json()["reservation"]["is_mine"])
        self.assertEqual(
            listing.json()["results"][0]["reservation"]["reviewer_name"],
            "Amina Khan",
        )

    def test_non_qa_and_calls_without_recordings_are_rejected(self):
        leader = User.objects.create_user(
            email="leader@example.com",
            password="a-very-strong-password",
            first_name="Team",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.client.force_login(leader)
        self.assertEqual(self.client.get(self.url("call-analysis")).status_code, 403)

        self.call.recording_download_status = CallEvent.Status.PENDING
        self.call.recording_path = ""
        self.call.save(update_fields=["recording_download_status", "recording_path"])
        self.client.force_login(self.qa_one)
        self.assertEqual(self.client.post(self.url("call-reserve")).status_code, 409)


class RecordingTaskConfigurationTests(TestCase):
    def test_recording_tasks_route_to_the_recordings_queue(self):
        for task in (resolve_recording, fetch_recording):
            route = celery_app.amqp.router.route({}, task.name, args=(), kwargs={})
            self.assertEqual(route["queue"].name, "recordings")

    def test_recording_tasks_are_rate_limited(self):
        self.assertEqual(resolve_recording.rate_limit, "2/s")
        self.assertEqual(fetch_recording.rate_limit, "1/s")


@override_settings(DIALER_CREDENTIAL_KEY=Fernet.generate_key().decode())
class RecordingDownloadRecoveryTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Recovery", slug="recovery")
        branch = Branch.objects.create(company=company, name="Karachi", code="khi")
        self.dialer = Dialer(
            branch=branch,
            name="Recovery dialer",
            api_url="https://dialer.example.com/non_agent_api.php",
            api_username="api",
        )
        self.dialer.set_api_password("secret")
        self.dialer.set_webhook_secret("long-recovery-webhook-secret")
        self.dialer.save()
        self.event = CallEvent.objects.create(
            dialer=self.dialer,
            branch=branch,
            event_key="recovery".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            lead_id="12345",
            agent_user="8014",
            source_recording_id="old-recording",
            recording_source_url="http://recordings.example.com/stale.wav",
        )

    @patch("apps.calls.tasks.lookup_recording")
    @patch("apps.calls.tasks.download_recording")
    def test_download_failure_refreshes_changed_url_and_downloads_immediately(
        self, download, lookup
    ):
        request = httpx.Request("GET", self.event.recording_source_url)
        response = httpx.Response(503, request=request)
        stale_error = httpx.HTTPStatusError(
            "stale recording URL", request=request, response=response
        )
        refreshed_url = "https://recordings.example.com/replaced.wav"
        lookup.return_value = RecordingResult(
            "2026-09-04 10:00:00",
            "8014",
            "new-recording",
            "12345",
            30,
            refreshed_url,
        )
        download.side_effect = [
            stale_error,
            ("/recordings/recovered.wav", 4096, "a" * 64),
        ]

        result = fetch_recording.apply(args=[str(self.event.pk)]).get()

        self.assertEqual(result, {"status": "downloaded", "bytes": 4096})
        self.event.refresh_from_db()
        self.assertEqual(self.event.recording_source_url, refreshed_url)
        self.assertEqual(self.event.source_recording_id, "new-recording")
        self.assertEqual(
            self.event.recording_download_status, CallEvent.Status.DOWNLOADED
        )
        self.assertEqual(
            [item.args[1] for item in download.call_args_list],
            ["http://recordings.example.com/stale.wav", refreshed_url],
        )
        lookup.assert_called_once()

    @patch("apps.calls.tasks.recording_duration_seconds", return_value=47)
    @patch("apps.calls.tasks.download_recording")
    def test_recording_duration_replaces_webhook_duration(self, download, duration):
        self.event.talk_time = 999
        self.event.save(update_fields=["talk_time"])
        recording_path = "/recordings/measured.wav"
        download.return_value = (recording_path, 4096, "a" * 64)

        result = fetch_recording.apply(args=[str(self.event.pk)]).get()

        self.assertEqual(result, {"status": "downloaded", "bytes": 4096})
        self.event.refresh_from_db()
        self.assertEqual(self.event.talk_time, 47)
        duration.assert_called_once_with(recording_path)

    @patch("apps.calls.tasks.lookup_recording")
    @patch("apps.calls.tasks.download_recording")
    def test_manually_requeued_failed_download_refreshes_before_download(
        self, download, lookup
    ):
        self.event.recording_download_status = CallEvent.Status.FAILED
        self.event.save(update_fields=["recording_download_status"])
        refreshed_url = "https://recordings.example.com/final.wav"
        lookup.return_value = RecordingResult(
            "2026-09-04 10:00:00",
            "8014",
            "final-recording",
            "12345",
            30,
            refreshed_url,
        )
        download.return_value = ("/recordings/final.wav", 1024, "b" * 64)

        result = fetch_recording.apply(args=[str(self.event.pk)]).get()

        self.assertEqual(result, {"status": "downloaded", "bytes": 1024})
        lookup.assert_called_once()
        self.assertEqual(download.call_args.args[1], refreshed_url)


class RecordingResponseParsingTests(SimpleTestCase):
    def test_recording_duration_is_read_from_downloaded_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duration.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 26_000)

            self.assertEqual(recording_duration_seconds(path), 3)

    def test_invalid_audio_duration_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.wav"
            path.write_bytes(b"not an audio file")

            self.assertIsNone(recording_duration_seconds(path))

    def test_rows_without_a_recording_location_are_ignored(self):
        response = "2026-09-04 01:02:03|agent01|42|123|30|"

        self.assertEqual(parse_recordings(response), [])

    def test_http_and_https_are_accepted_for_any_public_host(self):
        for scheme in ("http", "https"):
            with self.subTest(scheme=scheme):
                validate_recording_url(
                    f"{scheme}://unconfigured-recordings.example.com/audio/call.mp3"
                )

    def test_recording_url_validation_keeps_ssrf_guards_for_both_schemes(self):
        invalid_urls = [
            "ftp://recordings.example.com/audio/call.mp3",
            "http://user:password@recordings.example.com/audio/call.mp3",
            "http://127.0.0.1/audio/call.mp3",
            "/audio/call.mp3",
        ]

        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                validate_recording_url(url)

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
