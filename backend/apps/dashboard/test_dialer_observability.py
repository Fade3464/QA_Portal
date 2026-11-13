from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.calls.models import CallEvent
from apps.tenancy.models import Branch, Company, Dialer


class DialerManagerObservabilityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Observability Co", slug="observability-co")
        self.branch = Branch.objects.create(
            company=self.company, name="Main", code="OBS"
        )
        self.manager = User.objects.create_user(
            email="observability.manager@example.com",
            password="strong-temporary-password",
            first_name="Dialer",
            last_name="Observer",
            role=User.Role.DIALER_MANAGER,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.qa = User.objects.create_user(
            email="observability.qa@example.com",
            password="strong-temporary-password",
            first_name="QA",
            last_name="User",
            role=User.Role.QA,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.closer = Dialer.objects.create(
            branch=self.branch,
            name="Closer A",
            is_closer=True,
            api_url="https://closer.example.com/non_agent_api.php",
            api_username="api",
        )
        self.url = reverse("dialer-manager-observability")

    def create_sale(
        self,
        suffix,
        *,
        ingroup="INGROUP_A",
        list_name="List Alpha",
        call_direction=CallEvent.Direction.CLOSER,
        dial_method=CallEvent.DialMethod.AUTO,
        finalized_at=None,
    ):
        return CallEvent.objects.create(
            dialer=self.closer,
            branch=self.branch,
            event_key=f"obs-{suffix}",
            event_type=CallEvent.EventType.DISPOSITION,
            disposition="SALE",
            closer_group=ingroup,
            inbound_list_name=list_name,
            call_direction=call_direction,
            dial_method=dial_method,
            finalized_at=finalized_at or timezone.now(),
        )

    def test_tree_groups_closer_ingroup_lists_and_errors(self):
        self.create_sale("1", list_name="List Alpha")
        self.create_sale("2", list_name="List Alpha")
        self.create_sale("3", list_name="List Beta")
        self.create_sale("4", ingroup="INGROUP_B", list_name="ERROR: fronter API request failed")
        self.create_sale("5", ingroup="INGROUP_B", list_name=None)
        self.create_sale(
            "outbound",
            list_name="Should Not Appear",
            call_direction=CallEvent.Direction.OUTBOUND,
        )
        self.create_sale(
            "manual",
            list_name="Should Not Appear Either",
            dial_method=CallEvent.DialMethod.MANUAL,
        )

        self.client.force_login(self.manager)
        response = self.client.get(self.url, {"window": "today"})
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["totals"], {"sales": 5, "dialers": 1, "errors": 2})

        dialer = payload["dialers"][0]
        self.assertEqual(dialer["name"], "Closer A")
        self.assertEqual(dialer["sales"], 5)
        self.assertEqual(dialer["error_count"], 2)
        ingroups = {item["name"]: item for item in dialer["ingroups"]}
        self.assertEqual(ingroups["INGROUP_A"]["sales"], 3)
        self.assertEqual(
            {item["name"]: item["count"] for item in ingroups["INGROUP_A"]["lists"]},
            {"List Alpha": 2, "List Beta": 1},
        )
        self.assertEqual(ingroups["INGROUP_B"]["sales"], 2)
        self.assertEqual(ingroups["INGROUP_B"]["lists"], [])
        errors = {item["message"]: item["count"] for item in dialer["errors"]}
        self.assertEqual(errors["ERROR: fronter API request failed"], 1)
        self.assertEqual(errors["Unresolved list name"], 1)

    def test_time_window_excludes_old_sales(self):
        self.create_sale("current")
        self.create_sale("old", finalized_at=timezone.now() - timedelta(days=10))
        self.client.force_login(self.manager)
        response = self.client.get(self.url, {"window": "7d"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["totals"]["sales"], 1)

    def test_non_dialer_manager_is_denied(self):
        self.client.force_login(self.qa)
        self.assertEqual(self.client.get(self.url).status_code, 403)
