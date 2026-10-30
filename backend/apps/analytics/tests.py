from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.calls.models import CallEvent
from apps.tenancy.models import Branch, Company, Dialer, DialerCampaign, Team
from .services.sales import build_sales_dashboard


class SalesAnalyticsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Analytics Co", slug="analytics-co", analytics_enabled=True,
            grafana_viewer_username="analytics",
        )
        self.company.set_grafana_viewer_password("ExamplePass123!")
        self.company.save(update_fields=["grafana_viewer_password_ciphertext"])
        self.branch = Branch.objects.create(company=self.company, name="Main", code="main")
        self.leader = User.objects.create_user(
            email="leader@example.com", password="Password123!",
            first_name="Team", last_name="Lead", role=User.Role.TEAM_LEADER,
            company=self.company, branch=self.branch,
        )
        self.team = Team.objects.create(branch=self.branch, name="Alpha", team_leader=self.leader)
        self.dialer = Dialer(
            branch=self.branch, name="D1", api_url="https://dialer.example/api.php",
            api_username="api", api_source="tests",
        )
        self.dialer.set_api_password("api-password")
        self.dialer.set_webhook_secret("webhook-secret")
        self.dialer.save()
        DialerCampaign.objects.create(dialer=self.dialer, campaign="002", project_name="Medicare")
        now = timezone.now()
        self._call("sold", sold=True, preset="D42", twenty=True, thirty=True, when=now-timedelta(minutes=10))
        self._call("transfer", sold=False, preset="D33", twenty=True, when=now-timedelta(minutes=8))
        self._call("missing", sold=False, preset=None, when=now-timedelta(minutes=6))
        self._call("nonsale", disposition="DNC", when=now-timedelta(minutes=4))

    def _call(self, key, *, disposition="SALE", sold=False, preset=None, twenty=False, thirty=False, when=None, phone_number="", client_status=None):
        return CallEvent.objects.create(
            dialer=self.dialer, branch=self.branch, event_key=key,
            event_type=CallEvent.EventType.DISPOSITION,
            call_id=key, lead_id=key, agent_user="8102", agent_name="Agent One",
            team=self.team, team_name=self.team.name, campaign="002",
            disposition=disposition, sold=sold, preset=preset,
            client_20_plus=twenty, client_30_plus=thirty,
            call_date=when or timezone.now(), phone_number=phone_number,
            client_status=client_status,
        )

    def test_transfer_definition_and_grouped_metrics(self):
        now = timezone.now()
        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        summary = data["summary"][0]
        self.assertEqual(summary["opportunities"], 3)
        self.assertEqual(summary["sold"], 1)
        self.assertEqual(summary["transfers"], 2)
        self.assertEqual(summary["missing_preset"], 1)
        self.assertEqual(summary["twenty_plus"], 2)
        self.assertEqual(summary["thirty_plus"], 1)
        self.assertEqual(data["teams"][0]["team"], "Alpha")
        self.assertEqual(data["teams"][0]["team_leader"], "Team Lead")
        self.assertEqual(data["agents"][0]["team_leader"], "Team Lead")
        self.assertEqual(data["projects"][0]["project"], "Medicare")
        self.assertEqual(data["agent_table"][0]["D33"], 1)
        self.assertEqual(data["agent_table"][0]["D42"], 0)
        self.assertEqual(data["team_table"][0]["D33"], 1)
        self.assertEqual(data["team_table"][0]["D42"], 0)
        self.assertEqual(
            list(data["agent_table"][0]),
            [
                "Agent",
                "Team leader",
                "Sold",
                "30+",
                "Transfers",
                "Conversion %",
                "D33",
                "D42",
            ],
        )
        self.assertEqual(
            list(data["team_table"][0]),
            [
                "Team",
                "Team leader",
                "Sold",
                "30+",
                "Transfers",
                "Conversion %",
                "D33",
                "D42",
            ],
        )

    def test_preset_transfer_columns_only_exist_when_client_filter_is_all(self):
        now = timezone.now()
        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
            preset="D33",
        )
        self.assertEqual(
            list(data["agent_table"][0]),
            ["Agent", "Team leader", "Sold", "30+", "Transfers", "Conversion %"],
        )
        self.assertEqual(
            list(data["team_table"][0]),
            ["Team", "Team leader", "Sold", "30+", "Transfers", "Conversion %"],
        )

    def test_sold_detail_rows_include_expected_fields(self):
        now = timezone.now()
        self._call(
            "detail-sold",
            sold=True,
            preset="D77",
            thirty=True,
            when=now-timedelta(minutes=1),
            phone_number="15551234567",
            client_status="Confirmed",
        )
        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        detail = data["sold_details"][0]
        self.assertEqual(detail["agent"], "Agent One")
        self.assertEqual(detail["team"], "Alpha")
        self.assertEqual(detail["number"], "15551234567")
        self.assertEqual(detail["client"], "D77")
        self.assertEqual(detail["client_status"], "Confirmed")
        self.assertIn("T", detail["disposition_time"])

    def test_multiple_projects_can_be_selected_together(self):
        DialerCampaign.objects.create(
            dialer=self.dialer, campaign="003", project_name="Dental"
        )
        dental_call = self._call(
            "dental-sold",
            sold=True,
            preset="D99",
            when=timezone.now() - timedelta(minutes=2),
        )
        dental_call.campaign = "003"
        dental_call.save(update_fields=["campaign"])

        now = timezone.now()
        data = build_sales_dashboard(
            from_ms=str(int((now - timedelta(hours=1)).timestamp() * 1000)),
            to_ms=str(int(now.timestamp() * 1000)),
            project=["Medicare", "Dental"],
        )

        self.assertEqual(data["summary"][0]["opportunities"], 4)
        self.assertEqual(data["summary"][0]["sold"], 2)
        self.assertEqual(
            {row["project"] for row in data["projects"]}, {"Medicare", "Dental"}
        )
        self.assertEqual(data["trend_granularity"], "hour")
        self.assertLessEqual(len(data["top_agents"]), 10)

    @override_settings(GRAFANA_ANALYTICS_API_TOKEN="analytics-token")
    def test_grafana_endpoint_requires_internal_bearer_token(self):
        client = APIClient()
        path = "/api/v1/analytics/grafana/sales/"
        self.assertEqual(client.get(path).status_code, 403)
        response = client.get(path, HTTP_AUTHORIZATION="Bearer analytics-token")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])
        agent_table = client.get(
            path,
            {"section": "agent_table"},
            HTTP_AUTHORIZATION="Bearer analytics-token",
        )
        self.assertEqual(agent_table.status_code, 200)
        self.assertIsInstance(agent_table.json(), list)
        self.assertEqual(agent_table.json()[0]["Agent"], "Agent One")
