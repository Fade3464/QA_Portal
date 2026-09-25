from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.tenancy.models import Branch, Company

from .models import SystemNotification


class CustomNotificationApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="a-very-strong-password",
            first_name="System",
            last_name="Administrator",
            must_change_password=False,
        )
        self.company = Company.objects.create(name="Acme", slug="acme")
        self.branch = Branch.objects.create(
            company=self.company, name="New York", code="nyc"
        )
        self.other_company = Company.objects.create(name="Beacon", slug="beacon")
        self.other_branch = Branch.objects.create(
            company=self.other_company, name="Albany", code="alb"
        )
        self.qa = self._user("qa@example.com", "QA", User.Role.QA, self.branch)
        self.leader = self._user(
            "leader@example.com", "Leader", User.Role.TEAM_LEADER, self.branch
        )
        self.manager = self._user(
            "manager@example.com",
            "Manager",
            User.Role.PROJECT_MANAGER,
            self.other_branch,
        )
        self.inactive_qa = self._user(
            "inactive@example.com", "Inactive", User.Role.QA, self.branch, False
        )

    def _user(self, email, first_name, role, branch, is_active=True):
        return User.objects.create_user(
            email=email,
            password="a-very-strong-password",
            first_name=first_name,
            last_name="User",
            role=role,
            company=branch.company,
            branch=branch,
            is_active=is_active,
            must_change_password=False,
        )

    def _send(self, **overrides):
        payload = {
            "audience": "all",
            "target_ids": [],
            "severity": "info",
            "title": "Scheduled maintenance",
            "message": "The portal will be unavailable for ten minutes.",
            **overrides,
        }
        return self.client.post(
            reverse("notification-admin-broadcasts"),
            payload,
            content_type="application/json",
        )

    def test_only_system_administrators_can_broadcast(self):
        self.client.force_login(self.qa)
        self.assertEqual(self._send().status_code, 403)
        self.assertFalse(
            SystemNotification.objects.filter(
                category=SystemNotification.Category.CUSTOM
            ).exists()
        )

    @patch("apps.notifications.services._broadcast")
    def test_role_broadcast_is_persisted_deduplicated_and_announced(self, broadcast):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self._send(
                audience="roles", target_ids=[User.Role.QA, User.Role.QA]
            )
        self.assertEqual(response.status_code, 201, response.content)
        notification = SystemNotification.objects.get(
            category=SystemNotification.Category.CUSTOM
        )
        self.assertEqual(list(notification.recipients.all()), [self.qa])
        self.assertEqual(notification.metadata["audience_type"], "roles")
        self.assertEqual(notification.metadata["sender_id"], str(self.admin.pk))
        self.assertEqual(response.json()["recipient_count"], 1)
        broadcast.assert_called_once()
        group_name, payload = broadcast.call_args.args
        self.assertEqual(group_name, "role_qa")
        self.assertEqual(payload["notification"]["id"], str(notification.pk))

    def test_all_users_excludes_inactive_users_and_system_administrators(self):
        self.client.force_login(self.admin)
        response = self._send()
        self.assertEqual(response.status_code, 201, response.content)
        notification = SystemNotification.objects.get(
            category=SystemNotification.Category.CUSTOM
        )
        self.assertSetEqual(
            set(notification.recipients.all()), {self.qa, self.leader, self.manager}
        )
        self.assertNotIn(self.inactive_qa, notification.recipients.all())
        self.assertNotIn(self.admin, notification.recipients.all())

    def test_branch_targeting_and_recipient_visibility_are_strict(self):
        self.client.force_login(self.admin)
        response = self._send(audience="branches", target_ids=[str(self.branch.pk)])
        self.assertEqual(response.status_code, 201, response.content)
        notification = SystemNotification.objects.get(
            category=SystemNotification.Category.CUSTOM
        )
        self.assertSetEqual(set(notification.recipients.all()), {self.qa, self.leader})

        self.client.force_login(self.qa)
        qa_list = self.client.get(reverse("notification-list"))
        self.assertEqual(qa_list.status_code, 200)
        self.assertEqual(qa_list.json()["results"][0]["id"], str(notification.pk))

        self.client.force_login(self.manager)
        manager_list = self.client.get(reverse("notification-list"))
        self.assertEqual(manager_list.status_code, 200)
        self.assertEqual(manager_list.json()["results"], [])

        self.client.force_login(self.admin)
        admin_list = self.client.get(reverse("notification-list"))
        self.assertEqual(admin_list.status_code, 200)
        self.assertNotIn(
            str(notification.pk),
            [item["id"] for item in admin_list.json()["results"]],
        )
        history = self.client.get(reverse("notification-admin-broadcasts"))
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["results"][0]["recipient_count"], 2)

    def test_empty_audience_is_rejected_without_creating_notification(self):
        self.client.force_login(self.admin)
        response = self._send(audience="roles", target_ids=[User.Role.SUPERVISOR])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            SystemNotification.objects.filter(
                category=SystemNotification.Category.CUSTOM
            ).exists()
        )
