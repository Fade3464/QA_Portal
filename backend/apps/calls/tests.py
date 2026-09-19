import json
import secrets
import tempfile
import uuid
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.core import mail
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

from .models import CallEvent, Review, ReviewWorkflowEvent
from .scorecard import SCORECARD
from .serializers import CallEventSerializer
from .services import (
    RecordingResult,
    download_recording,
    lookup_recording,
    parse_call_date,
    parse_recordings,
    recording_duration_seconds,
    validate_recording_url,
)
from .tasks import fetch_recording, resolve_recording
from .webhooks import infer_call_direction, infer_dial_method
from apps.notifications.tasks import (
    send_review_report_email,
    send_review_returned_email,
)


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


@override_settings(TIME_ZONE="America/New_York")
class CallDateTimezoneTests(SimpleTestCase):
    def test_sql_date_uses_est_in_winter_and_edt_in_summer(self):
        winter = parse_call_date("2026-01-15 12:00:00")
        summer = parse_call_date("2026-07-15 12:00:00")

        self.assertEqual(winter.utcoffset(), timedelta(hours=-5))
        self.assertEqual(summer.utcoffset(), timedelta(hours=-4))

    def test_offset_bearing_timestamp_preserves_its_instant(self):
        parsed = parse_call_date("2026-07-15T12:00:00-04:00")

        self.assertEqual(parsed.astimezone(UTC), datetime(2026, 7, 15, 16, tzinfo=UTC))

    def test_nonexistent_spring_forward_time_is_rejected(self):
        self.assertIsNone(parse_call_date("2026-03-08 02:30:00"))

    def test_ambiguous_fall_back_time_uses_nearest_receipt_instant(self):
        daylight = parse_call_date(
            "2026-11-01 01:30:00",
            reference=datetime(2026, 11, 1, 5, 35, tzinfo=UTC),
        )
        standard = parse_call_date(
            "2026-11-01 01:30:00",
            reference=datetime(2026, 11, 1, 6, 35, tzinfo=UTC),
        )

        self.assertEqual(daylight.astimezone(UTC).hour, 5)
        self.assertEqual(standard.astimezone(UTC).hour, 6)


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

    def test_team_leader_call_library_and_filters_are_strictly_team_scoped(self):
        leader = User.objects.create_user(
            email="leader@example.com",
            password="a-very-strong-password",
            first_name="Amina",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        other_leader = User.objects.create_user(
            email="other-leader@example.com",
            password="a-very-strong-password",
            first_name="Bilal",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        own_team = Team.objects.create(
            branch=self.branch, name="Amina Team", team_leader=leader
        )
        other_team = Team.objects.create(
            branch=self.branch, name="Bilal Team", team_leader=other_leader
        )
        project = DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="SHARED",
            project_name="Shared Project",
        )
        QAProjectAssignment.objects.create(qa=leader, dialer_campaign=project)
        own_call = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            team=own_team,
            team_name=own_team.name,
            event_key="leader-own-team".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="shared",
            agent_name="Visible Agent",
            disposition="SALE",
        )
        CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            team=other_team,
            team_name=other_team.name,
            event_key="leader-other-team".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="shared",
            agent_name="Hidden Agent",
            disposition="HIDDEN",
        )
        CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="leader-unassigned".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="shared",
            agent_name="Unassigned Agent",
            disposition="UNASSIGNED",
        )

        self.client.force_login(leader)
        listing = self.client.get(reverse("call-list"))
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["count"], 1)
        self.assertEqual(
            [row["id"] for row in listing.json()["results"]], [str(own_call.pk)]
        )

        filters = self.client.get(reverse("call-filter-options"))
        self.assertEqual(filters.status_code, 200)
        self.assertEqual(filters.json()["agents"], ["Visible Agent"])
        self.assertEqual(filters.json()["teams"], [own_team.name])
        self.assertEqual(filters.json()["dispositions"], ["SALE"])

        dashboard = self.client.get(reverse("dashboard-summary"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["metrics"]["total_calls"], 1)
        self.assertEqual(
            [row["id"] for row in dashboard.json()["recent_calls"]],
            [str(own_call.pk)],
        )

    def test_project_manager_calls_reports_and_analytics_are_project_scoped(self):
        manager = User.objects.create_user(
            email="manager@example.com",
            password="a-very-strong-password",
            first_name="Priya",
            last_name="Manager",
            role=User.Role.PROJECT_MANAGER,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        reviewer = User.objects.create_user(
            email="project-qa@example.com",
            password="a-very-strong-password",
            first_name="Quality",
            last_name="Analyst",
            role=User.Role.QA,
            company=self.branch.company,
            branch=self.branch,
            must_change_password=False,
        )
        allowed_project = DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="PM-ALLOWED",
            project_name="Managed Project",
        )
        DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="PM-HIDDEN",
            project_name="Hidden Project",
        )
        QAProjectAssignment.objects.create(
            qa=manager, dialer_campaign=allowed_project
        )
        visible_call = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="pm-visible".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="pm-allowed",
            agent_name="Visible Agent",
        )
        active_call = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="pm-active".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="PM-ALLOWED",
            agent_name="Active Agent",
        )
        hidden_call = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="pm-hidden".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="PM-HIDDEN",
            agent_name="Hidden Agent",
        )
        visible_review = Review.objects.create(
            call=visible_call,
            reviewer=reviewer,
            status=Review.Status.COMPLETED,
            score=92,
            completed_at=timezone.now(),
        )
        active_review = Review.objects.create(
            call=active_call,
            reviewer=reviewer,
            status=Review.Status.IN_PROGRESS,
        )
        hidden_review = Review.objects.create(
            call=hidden_call,
            reviewer=reviewer,
            status=Review.Status.COMPLETED,
            score=40,
            critical_errors=["privacy_violation"],
            completed_at=timezone.now(),
        )

        self.client.force_login(manager)
        calls = self.client.get(reverse("call-list"))
        self.assertEqual(calls.status_code, 200)
        self.assertEqual(
            {row["id"] for row in calls.json()["results"]},
            {str(visible_call.pk), str(active_call.pk)},
        )

        reports = self.client.get(reverse("review-report-list"))
        self.assertEqual(reports.status_code, 200)
        self.assertEqual(
            {row["id"] for row in reports.json()["results"]},
            {str(visible_review.pk), str(active_review.pk)},
        )
        active_reports = self.client.get(
            reverse("review-report-list"), {"segment": "qa_active"}
        )
        self.assertEqual(active_reports.status_code, 200)
        self.assertEqual(
            [row["id"] for row in active_reports.json()["results"]],
            [str(active_review.pk)],
        )
        summary = self.client.get(reverse("review-report-summary"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["total"], 2)
        self.assertEqual(summary.json()["qa_active"], 1)
        self.assertEqual(summary.json()["pending"], 1)
        self.assertEqual(
            self.client.get(
                reverse("review-report-detail", kwargs={"pk": hidden_review.pk})
            ).status_code,
            404,
        )

        performance = self.client.get(reverse("project-performance"))
        self.assertEqual(performance.status_code, 200, performance.content)
        self.assertEqual(performance.json()["projects"], ["Managed Project"])
        self.assertEqual(performance.json()["metrics"]["evaluated"], 1)
        self.assertEqual(performance.json()["metrics"]["average_score"], 92.0)
        self.assertEqual(performance.json()["metrics"]["critical"], 0)

        action = self.client.post(
            reverse("review-report-action", kwargs={"pk": visible_review.pk}),
            {"leader_status": Review.LeaderStatus.ACKNOWLEDGED},
            content_type="application/json",
        )
        self.assertEqual(action.status_code, 403)

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
        self.team_leader = User.objects.create_user(
            email="analysis-leader@example.com",
            password="a-very-strong-password",
            first_name="Team",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=company,
            branch=self.branch,
            must_change_password=False,
        )
        self.team = Team.objects.create(
            branch=self.branch,
            name="Analysis Team",
            team_leader=self.team_leader,
        )
        for qa in (self.qa_one, self.qa_two):
            QAProjectAssignment.objects.create(qa=qa, dialer_campaign=campaign)
        QAProjectAssignment.objects.create(
            qa=self.team_leader, dialer_campaign=campaign
        )
        self.call = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="analysis-call".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="analysis",
            agent_user="8014",
            agent_name="Ayesha Agent",
            phone_number="+923001234567",
            team=self.team,
            team_name=self.team.name,
            talk_time=120,
            recording_download_status=CallEvent.Status.DOWNLOADED,
            recording_path="/recordings/analysis.wav",
        )

    def url(self, name):
        return reverse(name, kwargs={"pk": self.call.pk})

    def full_scores(self):
        return {
            key: maximum
            for category in SCORECARD
            for key, _label, maximum in category["criteria"]
        }

    def submission(self, **overrides):
        payload = {
            "scores": self.full_scores(),
            "critical_errors": [],
            "feedback_summary": "The agent handled the conversation professionally.",
            "strengths": "Clear communication and accurate disclosures.",
            "improvement_areas": "Confirm the next step more explicitly.",
            "expected_behavior": "Summarize the commitment before closing.",
            "coaching_plan": "Review the closing checklist with the Team Leader.",
        }
        payload.update(overrides)
        return payload

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
        self.assertFalse(detail.json()["call"]["reservation"]["is_mine"])
        self.assertEqual(detail.json()["scorecard"]["max_score"], 100)
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

    def test_draft_uses_server_calculated_score(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        response = self.client.patch(
            self.url("call-review-draft"),
            {"scores": {"professional_greeting": 1.5}, "strengths": "Warm tone."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "1.50")
        review = Review.objects.get(call=self.call)
        self.assertEqual(review.scorecard_version, "outbound-sales-v1")
        self.assertEqual(review.strengths, "Warm tone.")

    def test_partial_call_normalizes_quality_against_applicable_headings(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        applicable = {category["key"]: "not_reached" for category in SCORECARD}
        applicable.update({"opening": "applicable", "communication": "applicable"})
        reasons = {
            key: "caller_ended"
            for key, state in applicable.items()
            if state == "not_reached"
        }
        scores = {
            key: maximum
            for category in SCORECARD[:2]
            for key, _label, maximum in category["criteria"]
        }

        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                scores=scores,
                evaluation_type="partial",
                category_applicability=applicable,
                category_applicability_reasons=reasons,
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "100.00")
        self.assertEqual(response.json()["coverage"], "25.00")
        self.assertEqual(response.json()["coverage_tier"], "limited")
        self.assertEqual(response.json()["applicable_points"], "25.00")

    def test_insufficient_short_call_is_recorded_without_numeric_score(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        applicable = {category["key"]: "not_reached" for category in SCORECARD}
        applicable["opening"] = "applicable"
        reasons = {
            key: "caller_ended"
            for key, state in applicable.items()
            if state == "not_reached"
        }
        opening_scores = {
            key: maximum for key, _label, maximum in SCORECARD[0]["criteria"]
        }

        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                scores=opening_scores,
                evaluation_type="partial",
                category_applicability=applicable,
                category_applicability_reasons=reasons,
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["score"])
        self.assertEqual(response.json()["coverage"], "10.00")
        self.assertEqual(response.json()["rating"], "not_evaluable")

    def test_agent_ended_call_scores_missed_heading_as_zero(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        applicable = {category["key"]: "not_reached" for category in SCORECARD}
        applicable.update(
            {"opening": "applicable", "communication": "missed_opportunity"}
        )
        reasons = {
            key: "agent_failed_to_progress"
            for key, state in applicable.items()
            if state != "applicable"
        }
        opening_scores = {
            key: maximum for key, _label, maximum in SCORECARD[0]["criteria"]
        }

        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                scores=opening_scores,
                evaluation_type="agent_premature",
                category_applicability=applicable,
                category_applicability_reasons=reasons,
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "40.00")
        self.assertEqual(response.json()["coverage"], "25.00")
        communication_keys = {
            key for key, _label, _maximum in SCORECARD[1]["criteria"]
        }
        self.assertTrue(communication_keys <= response.json()["scores"].keys())
        self.assertTrue(
            all(response.json()["scores"][key] == 0 for key in communication_keys)
        )

    def test_non_evaluable_call_is_submitted_without_scorecard(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))

        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                scores={},
                evaluation_type="not_evaluable",
                evaluation_reason="voicemail",
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["score"])
        self.assertEqual(response.json()["coverage"], "0.00")
        self.assertEqual(response.json()["rating"], "not_evaluable")

    def test_draft_saves_criterion_comments_and_multiple_timestamp_patches(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        first_patch_id = str(uuid.uuid4())
        second_patch_id = str(uuid.uuid4())
        evidence = {
            "active_listening": {
                "comment": "The agent acknowledged the customer's concern.",
                "patches": [
                    {
                        "id": second_patch_id,
                        "start_ms": 22000,
                        "end_ms": 27500,
                        "comment": "Effective confirmation.",
                    },
                    {
                        "id": first_patch_id,
                        "start_ms": 8000,
                        "end_ms": 12250,
                        "comment": "Customer states the core concern.",
                    },
                ],
            }
        }
        response = self.client.patch(
            self.url("call-review-draft"),
            {"criterion_evidence": evidence},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        saved = response.json()["criterion_evidence"]["active_listening"]
        self.assertEqual(saved["comment"], evidence["active_listening"]["comment"])
        self.assertEqual(
            [patch["id"] for patch in saved["patches"]],
            [first_patch_id, second_patch_id],
        )

    def test_criterion_evidence_rejects_invalid_ranges_and_unknown_criteria(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        overlapping = self.client.patch(
            self.url("call-review-draft"),
            {
                "criterion_evidence": {
                    "active_listening": {
                        "comment": "Evidence",
                        "patches": [
                            {
                                "id": str(uuid.uuid4()),
                                "start_ms": 1000,
                                "end_ms": 5000,
                                "comment": "",
                            },
                            {
                                "id": str(uuid.uuid4()),
                                "start_ms": 4000,
                                "end_ms": 6000,
                                "comment": "",
                            },
                        ],
                    }
                }
            },
            content_type="application/json",
        )
        self.assertEqual(overlapping.status_code, 400)
        self.assertIn("cannot overlap", str(overlapping.json()))

        beyond_duration = self.client.patch(
            self.url("call-review-draft"),
            {
                "criterion_evidence": {
                    "active_listening": {
                        "comment": "",
                        "patches": [
                            {
                                "id": str(uuid.uuid4()),
                                "start_ms": 119000,
                                "end_ms": 125000,
                                "comment": "",
                            }
                        ],
                    }
                }
            },
            content_type="application/json",
        )
        self.assertEqual(beyond_duration.status_code, 400)
        self.assertIn("recording duration", str(beyond_duration.json()))

        unknown = self.client.patch(
            self.url("call-review-draft"),
            {"criterion_evidence": {"invented_criterion": {"comment": "No"}}},
            content_type="application/json",
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("Unknown criterion", str(unknown.json()))

    def test_completed_report_is_owned_by_qa_and_delivered_to_team_leader(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "100.00")
        self.assertEqual(response.json()["rating"], Review.Rating.EXCELLENT)
        self.assertEqual(
            response.json()["outcome"], Review.Outcome.EXCEEDS_EXPECTATIONS
        )
        review = Review.objects.get(call=self.call)
        self.assertEqual(review.reviewer, self.qa_one)
        self.assertEqual(review.team_leader, self.team_leader)
        self.assertEqual(review.status, Review.Status.COMPLETED)
        self.assertEqual(review.email_status, Review.EmailStatus.DISABLED)

        notification = SystemNotification.objects.get(
            category=SystemNotification.Category.QA_REPORT_READY
        )
        self.assertEqual(list(notification.recipients.all()), [self.team_leader])

        self.client.force_login(self.team_leader)
        reports = self.client.get(reverse("review-report-list")).json()
        notifications = self.client.get(reverse("notification-list")).json()
        self.assertEqual(reports["count"], 1)
        self.assertEqual(reports["results"][0]["reviewer_name"], "Amina Khan")
        self.assertEqual(notifications["unread_count"], 1)
        self.assertEqual(len(notifications["results"]), 1)
        self.assertEqual(
            notifications["results"][0]["metadata"]["review_id"], str(review.pk)
        )

    def test_submission_allows_optional_narrative_fields_to_be_blank(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                feedback_summary="",
                improvement_areas="",
                expected_behavior="",
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Review.Status.COMPLETED)

    def test_team_leader_report_summary_and_workflow_are_scoped_and_audited(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        submitted = self.client.post(
            self.url("call-review-submit"),
            self.submission(),
            content_type="application/json",
        )
        review_id = submitted.json()["id"]

        DialerCampaign.objects.create(
            dialer=self.dialer,
            campaign="UNASSIGNED",
            project_name="Hidden Project",
        )
        hidden_call = CallEvent.objects.create(
            dialer=self.dialer,
            branch=self.branch,
            event_key="leader-project-hidden".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            campaign="UNASSIGNED",
            agent_user="8015",
            team=self.team,
            team_name=self.team.name,
        )
        Review.objects.create(
            call=hidden_call,
            reviewer=self.qa_one,
            team_leader=self.team_leader,
            status=Review.Status.COMPLETED,
            completed_at=timezone.now(),
        )

        self.client.force_login(self.team_leader)
        summary = self.client.get(reverse("review-report-summary"))
        self.assertEqual(summary.status_code, 200, summary.content)
        self.assertEqual(summary.json()["total"], 1)
        self.assertEqual(summary.json()["pending"], 1)
        self.assertEqual(summary.json()["average_score"], 100.0)
        self.assertEqual(summary.json()["filters"]["projects"], ["Analysis Project"])

        acknowledged = self.client.post(
            reverse("review-report-action", kwargs={"pk": review_id}),
            {"leader_status": Review.LeaderStatus.ACKNOWLEDGED},
            content_type="application/json",
        )
        self.assertEqual(acknowledged.status_code, 200, acknowledged.content)
        self.assertEqual(
            acknowledged.json()["leader_status"],
            Review.LeaderStatus.ACKNOWLEDGED,
        )
        self.assertEqual(len(acknowledged.json()["workflow_events"]), 1)
        event = ReviewWorkflowEvent.objects.get(review_id=review_id)
        self.assertEqual(event.actor, self.team_leader)
        self.assertEqual(event.from_status, Review.LeaderStatus.PENDING)
        self.assertEqual(event.to_status, Review.LeaderStatus.ACKNOWLEDGED)
        self.assertIsNotNone(
            SystemNotification.objects.get(
                dedupe_key=f"qa-report:{review_id}"
            ).resolved_at
        )

        due_at = timezone.now() + timedelta(days=2)
        coaching = self.client.post(
            reverse("review-report-action", kwargs={"pk": review_id}),
            {
                "leader_status": Review.LeaderStatus.COACHING_PLANNED,
                "coaching_due_at": due_at.isoformat(),
                "note": "Review the closing checklist in the next coaching session.",
            },
            content_type="application/json",
        )
        self.assertEqual(coaching.status_code, 200, coaching.content)
        self.assertEqual(
            coaching.json()["leader_status"],
            Review.LeaderStatus.COACHING_PLANNED,
        )
        self.assertEqual(len(coaching.json()["workflow_events"]), 2)

    def test_team_leader_can_filter_heading_and_subheading_scores_server_side(self):
        scores = self.full_scores()
        low_scores = {**scores, "professional_greeting": 0}
        for index, (call_id, values, total) in enumerate(
            (("PERFECT", scores, 100), ("LOW-OPENING", low_scores, 98))
        ):
            call = CallEvent.objects.create(
                dialer=self.dialer,
                branch=self.branch,
                event_key=f"score-filter-{index}".ljust(64, "0"),
                event_type=CallEvent.EventType.DISPOSITION,
                campaign="analysis",
                call_id=call_id,
                agent_name=f"Agent {index}",
                team=self.team,
                team_name=self.team.name,
            )
            Review.objects.create(
                call=call,
                reviewer=self.qa_one,
                team_leader=self.team_leader,
                status=Review.Status.COMPLETED,
                score=total,
                scores=values,
                completed_at=timezone.now(),
            )

        self.client.force_login(self.team_leader)
        category_rule = json.dumps(
            [{"scope": "category", "key": "opening", "operator": "lt", "value": 9, "unit": "points"}]
        )
        category_response = self.client.get(
            reverse("review-report-list"), {"segment": "all", "score_rules": category_rule}
        )
        self.assertEqual(category_response.status_code, 200, category_response.content)
        self.assertEqual(category_response.json()["count"], 1)
        self.assertEqual(category_response.json()["results"][0]["call_id"], str(CallEvent.objects.get(call_id="LOW-OPENING").pk))

        any_rules = json.dumps(
            [
                {"scope": "criterion", "key": "professional_greeting", "operator": "eq", "value": 0, "unit": "points"},
                {"scope": "total", "key": "total", "operator": "eq", "value": 100, "unit": "percent"},
            ]
        )
        any_response = self.client.get(
            reverse("review-report-list"),
            {"segment": "all", "score_match": "any", "score_rules": any_rules},
        )
        self.assertEqual(any_response.status_code, 200, any_response.content)
        self.assertEqual(any_response.json()["count"], 2)

        invalid_response = self.client.get(
            reverse("review-report-list"),
            {"segment": "all", "score_rules": json.dumps([{"scope": "criterion", "key": "unknown", "operator": "eq", "value": 1}])},
        )
        self.assertEqual(invalid_response.status_code, 400)

    def test_team_leader_workflow_rejects_invalid_transition_and_qa_action(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        review_id = self.client.post(
            self.url("call-review-submit"),
            self.submission(),
            content_type="application/json",
        ).json()["id"]
        action_url = reverse("review-report-action", kwargs={"pk": review_id})

        denied = self.client.post(
            action_url,
            {"leader_status": Review.LeaderStatus.ACKNOWLEDGED},
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.team_leader)
        invalid = self.client.post(
            action_url,
            {"leader_status": Review.LeaderStatus.CLOSED},
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)
        missing_due_date = self.client.post(
            action_url,
            {
                "leader_status": Review.LeaderStatus.COACHING_PLANNED,
                "note": "Coaching is required.",
            },
            content_type="application/json",
        )
        self.assertEqual(missing_due_date.status_code, 400)

    def test_team_leader_can_return_report_and_qa_can_reassess_and_resubmit(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        submitted = self.client.post(
            self.url("call-review-submit"),
            self.submission(),
            content_type="application/json",
        )
        review_id = submitted.json()["id"]
        action_url = reverse("review-report-action", kwargs={"pk": review_id})

        self.client.force_login(self.team_leader)
        missing_reason = self.client.post(
            action_url,
            {"leader_status": Review.LeaderStatus.RETURNED_TO_QA},
            content_type="application/json",
        )
        self.assertEqual(missing_reason.status_code, 400)

        reason = "The timestamp does not support the selected critical finding."
        returned = self.client.post(
            action_url,
            {
                "leader_status": Review.LeaderStatus.RETURNED_TO_QA,
                "note": reason,
            },
            content_type="application/json",
        )
        self.assertEqual(returned.status_code, 200, returned.content)
        self.assertEqual(returned.json()["status"], Review.Status.REVISION_REQUIRED)
        self.assertEqual(
            returned.json()["leader_status"], Review.LeaderStatus.RETURNED_TO_QA
        )
        self.assertEqual(returned.json()["revision_reason"], reason)
        self.assertEqual(returned.json()["revision_count"], 1)
        return_notification = SystemNotification.objects.get(
            category=SystemNotification.Category.QA_REPORT_RETURNED
        )
        self.assertTrue(return_notification.recipients.filter(pk=self.qa_one.pk).exists())
        self.assertEqual(return_notification.metadata["reason"], reason)
        self.assertIsNone(return_notification.resolved_at)

        self.client.force_login(self.qa_one)
        analysis = self.client.get(self.url("call-analysis"))
        self.assertEqual(analysis.status_code, 200, analysis.content)
        self.assertEqual(
            analysis.json()["review"]["status"], Review.Status.REVISION_REQUIRED
        )
        self.assertEqual(analysis.json()["review"]["revision_reason"], reason)
        release = self.client.post(self.url("call-release"))
        self.assertEqual(release.status_code, 409)
        draft = self.client.patch(
            self.url("call-review-draft"),
            {"strengths": "Updated after the Team Leader review."},
            content_type="application/json",
        )
        self.assertEqual(draft.status_code, 200, draft.content)

        resubmitted = self.client.post(
            self.url("call-review-submit"),
            self.submission(strengths="Updated after the Team Leader review."),
            content_type="application/json",
        )
        self.assertEqual(resubmitted.status_code, 200, resubmitted.content)
        self.assertEqual(resubmitted.json()["status"], Review.Status.COMPLETED)
        self.assertEqual(
            resubmitted.json()["leader_status"], Review.LeaderStatus.PENDING
        )
        self.assertEqual(resubmitted.json()["revision_reason"], "")
        self.assertEqual(resubmitted.json()["revision_count"], 1)
        return_notification.refresh_from_db()
        self.assertIsNotNone(return_notification.resolved_at)
        events = list(
            ReviewWorkflowEvent.objects.filter(review_id=review_id).order_by(
                "created_at"
            )
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].to_status, Review.LeaderStatus.RETURNED_TO_QA)
        self.assertEqual(events[1].from_status, Review.LeaderStatus.RETURNED_TO_QA)
        self.assertEqual(events[1].to_status, Review.LeaderStatus.PENDING)
        leader_notification = SystemNotification.objects.get(
            dedupe_key=f"qa-report:{review_id}"
        )
        self.assertIsNone(leader_notification.resolved_at)

    def test_critical_error_overrides_perfect_score(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(critical_errors=["misrepresentation"]),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["score"], "100.00")
        self.assertEqual(response.json()["rating"], Review.Rating.AUTOMATIC_FAIL)
        self.assertEqual(
            response.json()["outcome"], Review.Outcome.IMMEDIATE_ESCALATION
        )

    def test_critical_error_submission_does_not_require_scorecard(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                scores={},
                critical_errors=["misrepresentation"],
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["score"])
        self.assertEqual(response.json()["rating"], Review.Rating.AUTOMATIC_FAIL)
        self.assertEqual(
            response.json()["outcome"], Review.Outcome.IMMEDIATE_ESCALATION
        )

    def test_critical_error_submission_preserves_timestamp_evidence(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        patch_id = str(uuid.uuid4())
        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                scores={},
                critical_errors=["misrepresentation"],
                critical_error_evidence={
                    "misrepresentation": {
                        "comment": "The agent made an unsupported assurance.",
                        "patches": [
                            {
                                "id": patch_id,
                                "start_ms": 12000,
                                "end_ms": 18500,
                                "comment": "Unsupported commitment",
                            }
                        ],
                    }
                },
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        evidence = response.json()["critical_error_evidence"]["misrepresentation"]
        self.assertEqual(evidence["comment"], "The agent made an unsupported assurance.")
        self.assertEqual(evidence["patches"][0]["id"], patch_id)

    def test_critical_evidence_requires_the_violation_to_be_selected(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        response = self.client.post(
            self.url("call-review-submit"),
            self.submission(
                critical_error_evidence={
                    "misrepresentation": {
                        "comment": "Not selected.",
                        "patches": [],
                    }
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("selected critical errors", str(response.json()))

    def test_submission_rejects_incomplete_or_manipulated_scores(self):
        self.client.force_login(self.qa_one)
        self.client.post(self.url("call-reserve"))
        incomplete = self.client.post(
            self.url("call-review-submit"),
            self.submission(scores={"professional_greeting": 2}),
            content_type="application/json",
        )
        self.assertEqual(incomplete.status_code, 400)
        excessive = self.client.patch(
            self.url("call-review-draft"),
            {"scores": {"professional_greeting": 20}},
            content_type="application/json",
        )
        self.assertEqual(excessive.status_code, 400)

    @override_settings(
        QA_REPORT_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="qa@example.com",
        FRONTEND_URL="https://qa.example.com",
    )
    def test_completed_report_email_task_is_idempotent(self):
        review = Review.objects.create(
            call=self.call,
            reviewer=self.qa_one,
            team_leader=self.team_leader,
            status=Review.Status.COMPLETED,
            score=95,
            rating=Review.Rating.EXCELLENT,
            outcome=Review.Outcome.EXCEEDS_EXPECTATIONS,
            feedback_summary="A strong call.",
            improvement_areas="Ask one more discovery question.",
            expected_behavior="Complete every discovery step.",
            email_status=Review.EmailStatus.PENDING,
            completed_at=timezone.now(),
        )
        first = send_review_report_email.apply(args=[str(review.pk)]).get()
        second = send_review_report_email.apply(args=[str(review.pk)]).get()
        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "already_sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.team_leader.email])

    @override_settings(
        QA_RETURN_EMAIL_ENABLED=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="qa@example.com",
        FRONTEND_URL="https://qa.example.com",
    )
    def test_returned_report_email_task_is_idempotent_and_targets_qa(self):
        review = Review.objects.create(
            call=self.call,
            reviewer=self.qa_one,
            team_leader=self.team_leader,
            status=Review.Status.REVISION_REQUIRED,
            leader_status=Review.LeaderStatus.RETURNED_TO_QA,
            revision_reason="Recheck the compliance evidence.",
            revision_count=1,
            revision_requested_at=timezone.now(),
            completed_at=timezone.now(),
        )
        event = ReviewWorkflowEvent.objects.create(
            review=review,
            actor=self.team_leader,
            event_type=ReviewWorkflowEvent.EventType.STATUS_CHANGED,
            from_status=Review.LeaderStatus.PENDING,
            to_status=Review.LeaderStatus.RETURNED_TO_QA,
            note=review.revision_reason,
            email_status=Review.EmailStatus.PENDING,
        )
        first = send_review_returned_email.apply(args=[str(event.pk)]).get()
        second = send_review_returned_email.apply(args=[str(event.pk)]).get()
        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "already_sent")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.qa_one.email])
        self.assertIn(review.revision_reason, mail.outbox[0].body)
        self.assertIn(f"/calls?analysis={self.call.pk}", mail.outbox[0].body)


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
