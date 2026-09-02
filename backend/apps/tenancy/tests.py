from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User

from .models import Branch, Company


class AdministrationApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="a-very-strong-password",
            first_name="System",
            last_name="Administrator",
            role=User.Role.ADMINISTRATOR,
            must_change_password=False,
        )
        self.company = Company.objects.create(name="Acme", slug="acme")
        self.branch = Branch.objects.create(company=self.company, name="Karachi", code="khi")

    def test_non_administrator_cannot_access_management_api(self):
        user = User.objects.create_user(
            email="qa@example.com",
            password="a-very-strong-password",
            first_name="Amina",
            last_name="Khan",
            role=User.Role.QA,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("administration-summary")).status_code, 403)

    def test_administrator_can_manage_tenants_and_users(self):
        self.client.force_login(self.admin)
        company_response = self.client.post(
            reverse("administration-company-list"),
            {"name": "Northstar", "slug": "northstar", "is_active": True},
            content_type="application/json",
        )
        self.assertEqual(company_response.status_code, 201)
        branch_response = self.client.post(
            reverse("administration-branch-list"),
            {
                "company": company_response.json()["id"],
                "name": "Lahore",
                "code": "lhe",
                "timezone": "Asia/Karachi",
                "is_active": True,
            },
            content_type="application/json",
        )
        self.assertEqual(branch_response.status_code, 201)
        user_response = self.client.post(
            reverse("administration-user-list"),
            {
                "email": "lead@example.com",
                "first_name": "Team",
                "last_name": "Lead",
                "role": User.Role.TEAM_LEADER,
                "company": company_response.json()["id"],
                "branch": branch_response.json()["id"],
                "password": "temporary-strong-password",
                "is_active": True,
                "must_change_password": True,
            },
            content_type="application/json",
        )
        self.assertEqual(user_response.status_code, 201)
        self.assertEqual(str(User.objects.get(email="lead@example.com").branch_id), branch_response.json()["id"])
        dialer_response = self.client.post(
            reverse("administration-dialer-list"),
            {
                "branch": branch_response.json()["id"],
                "name": "Primary VICIdial",
                "api_url": "https://dialer.example.com/non_agent_api.php",
                "api_username": "qa-api",
                "api_password": "private-api-password",
                "api_source": "qa_portal",
                "webhook_secret": "a-long-private-webhook-secret",
                "request_timeout_seconds": 15,
                "is_active": True,
            },
            content_type="application/json",
        )
        self.assertEqual(dialer_response.status_code, 201)
        dialer = self.branch.__class__.objects.get(pk=branch_response.json()["id"]).dialers.get()
        self.assertEqual(dialer.get_api_password(), "private-api-password")
        self.assertTrue(dialer.check_webhook_secret("a-long-private-webhook-secret"))

    def test_administration_summary_returns_operational_counts(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("administration-summary"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["companies"], 1)
        self.assertEqual(response.json()["branches"], 1)
