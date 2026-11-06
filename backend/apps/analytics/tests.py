from io import BytesIO
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.calls.models import CallEvent
from apps.tenancy.models import Branch, Company, Dialer, DialerCampaign, Team
from .services.sales import build_sales_dashboard
from .services.xlsx import build_sales_xlsx


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

    def _call(self, key, *, disposition="SALE", sold=False, preset=None, twenty=False, thirty=False, when=None, phone_number="", client_status=None, agent_user="8102", agent_name="Agent One", closer_group=""):
        return CallEvent.objects.create(
            dialer=self.dialer, branch=self.branch, event_key=key,
            event_type=CallEvent.EventType.DISPOSITION,
            call_id=key, lead_id=key, agent_user=agent_user, agent_name=agent_name,
            team=self.team, team_name=self.team.name, campaign="002",
            disposition=disposition, sold=sold, preset=preset,
            client_20_plus=(twenty or thirty), client_30_plus=thirty,
            call_date=when or timezone.now(), phone_number=phone_number,
            client_status=client_status, closer_group=closer_group,
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
        self.assertEqual(summary["transfers"], 3)
        self.assertEqual(summary["missing_preset"], 1)
        self.assertEqual(summary["twenty_plus"], 2)
        self.assertEqual(summary["thirty_plus"], 1)
        self.assertEqual(data["teams"][0]["team"], "Alpha")
        self.assertEqual(data["teams"][0]["team_leader"], "Team Lead")
        self.assertEqual(data["agents"][0]["team_leader"], "Team Lead")
        self.assertEqual(data["projects"][0]["project"], "Medicare")
        self.assertEqual(data["teams"][0]["transfers"], 3)
        self.assertEqual(data["projects"][0]["transfers"], 3)
        self.assertEqual(data["presets"][0]["transfers"] + data["presets"][1]["transfers"] + data["presets"][2]["transfers"], 3)
        self.assertEqual(data["agent_table"][0]["D33"], 1)
        self.assertEqual(data["agent_table"][0]["D42"], 1)
        # Leaderboard conversion is all SALE dispositions (Transfers) divided by
        # all finalized call records for the agent in the selected time range.
        self.assertEqual(data["agent_table"][0]["Conversion %"], 75.0)
        self.assertEqual(data["team_table"][0]["D33"], 1)
        self.assertEqual(data["team_table"][0]["D42"], 1)
        preset_rows = {row["preset"]: row for row in data["presets"]}
        self.assertEqual(preset_rows["D42"]["transfers"], 1)
        self.assertEqual(preset_rows["D33"]["transfers"], 1)
        self.assertEqual(preset_rows["Unresolved"]["transfers"], 1)
        self.assertEqual(data["teams"][0]["agent_count"], 1)
        self.assertEqual(data["teams"][0]["kpi"], 1.0)
        self.assertEqual(data["projects"][0]["agent_count"], 1)
        self.assertEqual(data["projects"][0]["kpi"], 1.0)
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
                "Agent count",
                "Sold",
                "KPI",
                "30+",
                "Transfers",
                "Conversion %",
                "D33",
                "D42",
            ],
        )

    def test_active_agent_without_sale_still_appears_with_zero_metrics(self):
        now = timezone.now()
        self._call(
            "active-no-sale",
            disposition="DNC",
            when=now-timedelta(minutes=2),
            agent_user="8200",
            agent_name="Agent Zero",
        )

        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )

        row = next(item for item in data["agents"] if item["agent"] == "Agent Zero")
        self.assertEqual(row["team_leader"], "Team Lead")
        self.assertEqual(row["sold"], 0)
        self.assertEqual(row["transfers"], 0)
        self.assertEqual(row["conversion_pct"], 0.0)

        table_row = next(
            item for item in data["agent_table"] if item["Agent"] == "Agent Zero"
        )
        self.assertEqual(table_row["Sold"], 0)
        self.assertEqual(table_row["30+"], 0)
        self.assertEqual(table_row["Transfers"], 0)
        self.assertEqual(table_row["Conversion %"], 0.0)

        # Client filtering changes SALE metrics, but should not remove an agent
        # who had ordinary call activity inside the selected time/team/project.
        filtered = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
            preset="D33",
        )
        filtered_row = next(
            item for item in filtered["agent_table"] if item["Agent"] == "Agent Zero"
        )
        self.assertEqual(filtered_row["Transfers"], 0)
        self.assertEqual(filtered_row["Conversion %"], 0.0)

    def test_team_and_project_kpi_counts_agents_with_any_submitted_call(self):
        now = timezone.now()
        # Agent Two has no SALE at all. A completed DNC call must still make
        # them part of the distinct active-agent denominator for Team/Project.
        self._call(
            "second-agent-dnc",
            disposition="DNC",
            when=now-timedelta(minutes=1),
            agent_user="8201",
            agent_name="Agent Two",
        )
        self._call(
            "undisposed-agent",
            disposition="",
            when=now-timedelta(seconds=30),
            agent_user="8202",
            agent_name="Undisposed Agent",
        )

        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )

        team = next(row for row in data["teams"] if row["team"] == "Alpha")
        project = next(row for row in data["projects"] if row["project"] == "Medicare")
        self.assertEqual(team["agent_count"], 2)
        self.assertEqual(team["sold"], 1)
        self.assertEqual(team["kpi"], 0.5)
        self.assertEqual(project["agent_count"], 2)
        self.assertEqual(project["sold"], 1)
        self.assertEqual(project["kpi"], 0.5)

    def test_live_new_agent_is_excluded_from_leaderboard_activity(self):
        now = timezone.now()
        self._call(
            "live-new",
            disposition="NEW",
            when=now-timedelta(minutes=1),
            agent_user="8300",
            agent_name="Live Agent",
        )

        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )

        self.assertNotIn("Live Agent", {row["agent"] for row in data["agents"]})
        self.assertNotIn("Live Agent", {row["Agent"] for row in data["agent_table"]})

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
            ["Team", "Team leader", "Agent count", "Sold", "KPI", "30+", "Transfers", "Conversion %"],
        )

    def test_closer_group_filter_limits_dashboard_and_lists_available_groups(self):
        now = timezone.now()
        self._call(
            "closer-a",
            preset="D70",
            closer_group="CLOSER-A",
            when=now-timedelta(seconds=20),
        )
        self._call(
            "closer-b",
            preset="D71",
            closer_group="CLOSER-B",
            when=now-timedelta(seconds=10),
        )

        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
            closer_group="closer-a",
        )

        self.assertEqual(data["summary"][0]["opportunities"], 1)
        self.assertEqual(data["summary"][0]["transfers"], 1)
        self.assertEqual(
            {item["value"] for item in data["filters"]["closer_groups"]},
            {"CLOSER-A", "CLOSER-B"},
        )

    def test_state_geography_uses_area_code_and_preserves_transfer_definition(self):
        now = timezone.now()
        self._call(
            "geo-tx-transfer",
            sold=False,
            when=now-timedelta(seconds=40),
            phone_number="+1 (214) 555-0101",
        )
        self._call(
            "geo-tx-sold",
            sold=True,
            when=now-timedelta(seconds=30),
            phone_number="1-214-555-0102",
        )
        self._call(
            "geo-fl-transfer",
            sold=False,
            when=now-timedelta(seconds=20),
            phone_number="3055550103",
        )
        self._call(
            "geo-unmapped-toll-free",
            sold=True,
            when=now-timedelta(seconds=10),
            phone_number="8005550104",
        )

        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )

        geography = {row["state"]: row for row in data["state_geography"]}
        self.assertEqual(set(geography), {"TX", "FL"})
        self.assertEqual(geography["TX"], {"state": "TX", "transfers": 2, "sold": 1})
        self.assertEqual(geography["FL"], {"state": "FL", "transfers": 1, "sold": 0})
        self.assertEqual(
            data["state_transfer_heatmap"],
            data["state_geography"],
        )
        self.assertEqual(
            data["state_sold_heatmap"],
            [{"state": "TX", "transfers": 2, "sold": 1}],
        )

    def test_sold_detail_rows_include_expected_fields(self):
        now = timezone.now()
        edited_at = now - timedelta(seconds=15)
        event = self._call(
            "detail-sold",
            sold=True,
            preset="D77",
            thirty=True,
            when=now-timedelta(minutes=1),
            phone_number="15551234567",
            client_status="Confirmed",
        )
        CallEvent.objects.filter(pk=event.pk).update(edited_at=edited_at)
        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        detail = data["sold_details"][0]
        self.assertEqual(detail["agent"], "Agent One")
        self.assertEqual(detail["team"], "Alpha")
        self.assertEqual(detail["number"], "15551234567")
        self.assertEqual(detail["client"], "D77")
        self.assertEqual(detail["sale_status"], "Confirmed")
        self.assertEqual(detail["client_status"], "Confirmed")
        self.assertIn("T", detail["disposition_time"])
        self.assertEqual(detail["edited_at"], edited_at.isoformat())
        self.assertNotIn("number_style", detail)

    def test_sold_details_also_include_unsold_thirty_plus_as_sale_chance(self):
        now = timezone.now()
        self._call(
            "detail-thirty-plus-unsold",
            sold=False,
            preset="D91",
            thirty=True,
            when=now-timedelta(seconds=30),
            phone_number="15550003030",
            client_status="Follow-up",
        )
        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        detail = next(
            row for row in data["sold_details"] if row["number"] == "15550003030"
        )
        self.assertEqual(detail["client"], "D91")
        self.assertEqual(detail["sale_status"], "Only 30+")
        self.assertEqual(detail["client_status"], "Follow-up")
        self.assertNotIn("number_style", detail)

    def test_sold_details_exclude_unsold_calls_below_thirty_plus(self):
        now = timezone.now()
        self._call(
            "detail-below-thirty-unsold",
            sold=False,
            preset="D92",
            twenty=True,
            thirty=False,
            when=now-timedelta(seconds=20),
            phone_number="15550002020",
        )
        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        self.assertNotIn(
            "15550002020", {row["number"] for row in data["sold_details"]}
        )

    def test_transfer_detail_rows_include_expected_fields(self):
        now = timezone.now()
        self._call(
            "detail-transfer",
            sold=False,
            preset="D88",
            when=now-timedelta(minutes=1),
            phone_number="15557654321",
            client_status="Pending",
        )
        self._call(
            "detail-transfer-thirty",
            sold=False,
            preset="D89",
            thirty=True,
            when=now-timedelta(seconds=45),
            phone_number="15550003031",
        )
        self._call(
            "detail-transfer-sold",
            sold=True,
            preset="D90",
            when=now-timedelta(seconds=30),
            phone_number="15550009999",
        )
        data = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        detail = next(
            row for row in data["transfer_details"] if row["number"] == "15557654321"
        )
        self.assertEqual(detail["agent"], "Agent One")
        self.assertEqual(detail["team"], "Alpha")
        self.assertEqual(detail["client"], "D88")
        self.assertEqual(detail["client_status"], "Pending")
        self.assertIn("T", detail["disposition_time"])
        detail_numbers = {row["number"] for row in data["transfer_details"]}
        self.assertNotIn("15550003031", detail_numbers)
        self.assertNotIn("15550009999", detail_numbers)

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

    def test_sales_and_30plus_xlsx_has_sale_status_without_number_highlight(self):
        now = timezone.now()
        self._call(
            "xlsx-sold",
            sold=True,
            preset="D77",
            thirty=True,
            when=now-timedelta(seconds=20),
            phone_number="15551234567",
        )
        self._call(
            "xlsx-thirty",
            sold=False,
            preset="D78",
            thirty=True,
            when=now-timedelta(seconds=10),
            phone_number="15557654321",
        )
        payload = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        content, filename = build_sales_xlsx(payload, "sold_30plus")
        self.assertEqual(filename, "sold-30plus.xlsx")
        wb = load_workbook(BytesIO(content))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        self.assertEqual(
            headers,
            ["Agent", "Team", "Number", "Client", "Sale Status", "Client status", "Disposition time", "Edited at"],
        )
        rows = {ws.cell(row=i, column=3).value: i for i in range(2, ws.max_row + 1)}
        sold_row = rows["15551234567"]
        chance_row = rows["15557654321"]
        self.assertEqual(ws.cell(sold_row, 5).value, "Confirmed")
        self.assertEqual(ws.cell(chance_row, 5).value, "Only 30+")
        self.assertNotEqual(ws.cell(sold_row, 3).fill.fill_type, "solid")
        self.assertNotEqual(ws.cell(chance_row, 3).fill.fill_type, "solid")

    def test_agent_xlsx_contains_bold_cumulative_footer(self):
        now = timezone.now()
        payload = build_sales_dashboard(
            from_ms=str(int((now-timedelta(hours=1)).timestamp()*1000)),
            to_ms=str(int(now.timestamp()*1000)),
        )
        content, _ = build_sales_xlsx(payload, "agent")
        wb = load_workbook(BytesIO(content))
        ws = wb.active
        self.assertEqual([c.value for c in ws[1]][:5], [
            "Agent", "Team leader", "30+", "Transfers", "Conversion %"
        ])
        self.assertNotIn("Sold", [c.value for c in ws[1]])
        footer = ws.max_row
        self.assertTrue(all(cell.font.bold for cell in ws[footer]))
        self.assertEqual(ws.cell(footer, 1).value, 1)
        self.assertEqual(ws.cell(footer, 2).value, 1)
        self.assertEqual(ws.cell(footer, 4).value, 3)
        self.assertEqual(ws.cell(footer, 5).number_format, "0.00%")

    def test_xlsx_export_endpoint_requires_authenticated_grafana_proxy(self):
        client = APIClient()
        path = "/api/v1/analytics/grafana/export/xlsx/"
        self.assertEqual(client.get(path, {"table": "team"}).status_code, 403)
        response = client.get(
            path,
            {"table": "team"},
            HTTP_X_GRAFANA_EXPORT_AUTHORIZED="1",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("attachment;", response["Content-Disposition"])

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
