from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from django.test import TestCase, override_settings

from apps.tenancy.models import Branch, Company, Dialer, DialerFronterMapping

from .inbound_list_lookup import lookup_inbound_sale_list_name
from .models import CallEvent
from .tasks import resolve_sale_inbound_list, resolve_sale_preset


@override_settings(DIALER_CREDENTIAL_KEY=Fernet.generate_key().decode())
class InboundSaleListLookupTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Inbound Lookup Co", slug="inbound-lookup")
        branch = Branch.objects.create(
            company=company,
            name="Eastern",
            code="east",
            timezone="America/New_York",
        )
        self.closer = Dialer(
            branch=branch,
            name="Closer",
            is_closer=True,
            api_url="https://closer.example.com/vicidial/non_agent_api.php",
            api_username="closer-api",
        )
        self.closer.set_api_password("closer-secret")
        self.closer.save()

        self.fronter = Dialer(
            branch=branch,
            name="Fronter",
            is_closer=False,
            api_url="https://fronter.example.com/vicidial/non_agent_api.php",
            api_username="fronter-api",
            api_source="qa_portal",
        )
        self.fronter.set_api_password("fronter-secret")
        self.fronter.save()

        DialerFronterMapping.objects.create(
            closer_dialer=self.closer,
            fronter_dialer=self.fronter,
            ingroup_name="MEDI_A, MEDI_B",
        )
        self.event = CallEvent.objects.create(
            dialer=self.closer,
            branch=branch,
            event_key="inbound-list-sale".ljust(64, "0"),
            event_type=CallEvent.EventType.DISPOSITION,
            call_id="V-CLOSER-SALE-1",
            phone_number="6067865998",
            closer_group="MEDI_B",
            disposition="SALE",
            call_direction=CallEvent.Direction.CLOSER,
            dial_method=CallEvent.DialMethod.NOT_APPLICABLE,
            call_date=datetime(2026, 11, 14, 10, 30, tzinfo=ZoneInfo("America/New_York")),
            finalized_at=datetime(2026, 11, 14, 10, 45, tzinfo=ZoneInfo("America/New_York")),
        )

    @patch("apps.calls.inbound_list_lookup.httpx.Client")
    def test_resolves_mapped_fronter_list_name_for_same_date(self, client_factory):
        client = client_factory.return_value.__enter__.return_value
        phone_response = Mock()
        phone_response.text = """phone_number|call_date|list_id|length_in_sec|lead_status|hangup_reason|call_status|source_id|user
6067865998|2026-11-13 15:00:00|100|20|NA|AGENT|NA|old|7001
6067865998|2026-11-14 09:00:00|200|40|XFER|AGENT|XFER|first|7002
6067865998|2026-11-14 10:15:00|201|50|XFER|AGENT|XFER|nearest|7003
6067865998|2026-11-14 11:00:00|202|60|SALE|AGENT|SALE|later|7004
"""
        phone_response.raise_for_status.return_value = None
        list_response = Mock()
        list_response.text = """list_id|list_name|campaign_id|active|list_changedate|list_lastcalldate|expiration_date|resets_today
201|November Medicare Batch|FRONT|Y|2026-11-01 00:00:00|2026-11-14 10:15:00|2099-12-31|0
"""
        list_response.raise_for_status.return_value = None
        client.get.side_effect = [phone_response, list_response]

        result = lookup_inbound_sale_list_name(self.event)

        self.assertEqual(result, "November Medicare Batch")
        first_params = client.get.call_args_list[0].kwargs["params"]
        self.assertEqual(first_params["function"], "phone_number_log")
        self.assertEqual(first_params["phone_number"], "6067865998")
        self.assertEqual(first_params["type"], "OUT")
        second_params = client.get.call_args_list[1].kwargs["params"]
        self.assertEqual(second_params["function"], "list_info")
        self.assertEqual(second_params["list_id"], "201")

    def test_terminal_mapping_failure_is_written_to_call_event(self):
        self.event.closer_group = "UNMAPPED_GROUP"
        self.event.save(update_fields=["closer_group"])

        result = resolve_sale_inbound_list.run(str(self.event.pk))

        self.assertEqual(result["status"], "error")
        self.event.refresh_from_db()
        self.assertEqual(
            self.event.inbound_list_name,
            "ERROR: no fronter mapping for in-group UNMAPPED_GROUP",
        )

    @patch("apps.calls.tasks.resolve_missing_preset_notification")
    @patch("apps.calls.tasks.resolve_sale_inbound_list.delay")
    def test_inbound_list_work_is_queued_after_preset_work_finishes(
        self, inbound_lookup_delay, resolve_notification
    ):
        self.event.preset = "D42"
        self.event.save(update_fields=["preset"])

        result = resolve_sale_preset.run(str(self.event.pk))

        self.assertEqual(result["status"], "already_resolved")
        inbound_lookup_delay.assert_called_once_with(str(self.event.pk))
        resolve_notification.assert_called_once()

    @patch("apps.calls.tasks.resolve_missing_preset_notification")
    @patch("apps.calls.tasks.resolve_sale_inbound_list.delay")
    def test_outbound_sale_is_not_queued_after_preset_work(
        self, inbound_lookup_delay, resolve_notification
    ):
        self.event.preset = "D42"
        self.event.call_direction = CallEvent.Direction.OUTBOUND
        self.event.save(update_fields=["preset", "call_direction"])

        result = resolve_sale_preset.run(str(self.event.pk))

        self.assertEqual(result["status"], "already_resolved")
        inbound_lookup_delay.assert_not_called()
        resolve_notification.assert_called_once()

    @patch("apps.calls.tasks.resolve_missing_preset_notification")
    @patch("apps.calls.tasks.resolve_sale_inbound_list.delay")
    def test_manual_sale_is_not_queued_after_preset_work(
        self, inbound_lookup_delay, resolve_notification
    ):
        self.event.preset = "D42"
        self.event.dial_method = CallEvent.DialMethod.MANUAL
        self.event.save(update_fields=["preset", "dial_method"])

        result = resolve_sale_preset.run(str(self.event.pk))

        self.assertEqual(result["status"], "already_resolved")
        inbound_lookup_delay.assert_not_called()
        resolve_notification.assert_called_once()

    @patch("apps.calls.tasks.lookup_inbound_sale_list_name")
    def test_outbound_sale_never_calls_fronter_lookup(self, lookup):
        self.event.call_direction = CallEvent.Direction.OUTBOUND
        self.event.save(update_fields=["call_direction"])

        result = resolve_sale_inbound_list.run(str(self.event.pk))

        self.assertEqual(result["status"], "not_inbound")
        lookup.assert_not_called()
        self.event.refresh_from_db()
        self.assertIsNone(self.event.inbound_list_name)

    @patch("apps.calls.tasks.lookup_inbound_sale_list_name")
    def test_manual_sale_never_calls_fronter_lookup(self, lookup):
        self.event.dial_method = CallEvent.DialMethod.MANUAL
        self.event.save(update_fields=["dial_method"])

        result = resolve_sale_inbound_list.run(str(self.event.pk))

        self.assertEqual(result["status"], "not_inbound")
        lookup.assert_not_called()
        self.event.refresh_from_db()
        self.assertIsNone(self.event.inbound_list_name)

    @patch("apps.calls.tasks.lookup_inbound_sale_list_name")
    def test_sale_without_ingroup_never_calls_fronter_lookup(self, lookup):
        self.event.closer_group = ""
        self.event.save(update_fields=["closer_group"])

        result = resolve_sale_inbound_list.run(str(self.event.pk))

        self.assertEqual(result["status"], "not_inbound")
        lookup.assert_not_called()
        self.event.refresh_from_db()
        self.assertIsNone(self.event.inbound_list_name)

