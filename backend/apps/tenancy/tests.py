from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User

from .models import Branch, Company, Dialer, DialerCampaign, QAProjectAssignment, Team


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
        self.branch = Branch.objects.create(
            company=self.company, name="Karachi", code="khi"
        )

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
        self.assertEqual(
            self.client.get(reverse("administration-summary")).status_code, 403
        )

    def test_administrator_selects_a_team_avatar(self):
        leader = User.objects.create_user(
            email="avatar-leader@example.com",
            password="a-very-strong-password",
            first_name="Avatar",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration-team-list"),
            {
                "branch": str(self.branch.pk),
                "name": "Guardians",
                "avatar": "shield",
                "team_leader": str(leader.pk),
                "is_active": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["avatar"], "shield")
        self.assertEqual(Team.objects.get(name="Guardians").avatar, "shield")

    def test_team_avatar_rejects_unsafe_symbol_names(self):
        leader = User.objects.create_user(
            email="unsafe-avatar@example.com",
            password="a-very-strong-password",
            first_name="Safe",
            last_name="Leader",
            role=User.Role.TEAM_LEADER,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration-team-list"),
            {
                "branch": str(self.branch.pk),
                "name": "Unsafe",
                "avatar": "<script>",
                "team_leader": str(leader.pk),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Team.objects.filter(name="Unsafe").exists())

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
        self.assertEqual(
            str(User.objects.get(email="lead@example.com").branch_id),
            branch_response.json()["id"],
        )
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
                "campaigns": [
                    {"campaign": "RETENTION", "project_name": "Customer Retention"},
                    {"campaign": "SALES", "project_name": "Direct Sales"},
                ],
                "is_active": True,
            },
            content_type="application/json",
        )
        self.assertEqual(dialer_response.status_code, 201)
        dialer = self.branch.__class__.objects.get(
            pk=branch_response.json()["id"]
        ).dialers.get()
        self.assertEqual(dialer.get_api_password(), "private-api-password")
        self.assertTrue(dialer.check_webhook_secret("a-long-private-webhook-secret"))
        self.assertEqual(dialer.campaigns.count(), 2)
        self.assertEqual(
            dialer.campaigns.get(campaign="RETENTION").project_name,
            "Customer Retention",
        )
        self.assertEqual(len(dialer_response.json()["campaigns"]), 2)

    def test_dialer_rejects_duplicate_campaign_codes_case_insensitively(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration-dialer-list"),
            {
                "branch": str(self.branch.id),
                "name": "Duplicate campaign dialer",
                "api_url": "https://dialer.example.com/non_agent_api.php",
                "api_username": "qa-api",
                "api_password": "private-api-password",
                "api_source": "qa_portal",
                "webhook_secret": "a-long-private-webhook-secret",
                "campaigns": [
                    {"campaign": "SALES", "project_name": "Direct Sales"},
                    {"campaign": "sales", "project_name": "Other Project"},
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(DialerCampaign.objects.count(), 0)

    def test_administrator_assigns_qa_to_projects_in_the_same_branch(self):
        dialer = Dialer(
            branch=self.branch,
            name="Primary",
            api_url="https://dialer.example.com/non_agent_api.php",
            api_username="api",
        )
        dialer.set_api_password("secret")
        dialer.set_webhook_secret("a-long-private-webhook-secret")
        dialer.save()
        project = DialerCampaign.objects.create(
            dialer=dialer,
            campaign="SALES",
            project_name="Direct Sales",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration-user-list"),
            {
                "email": "qa-project@example.com",
                "first_name": "Project",
                "last_name": "Reviewer",
                "role": User.Role.QA,
                "company": str(self.company.pk),
                "branch": str(self.branch.pk),
                "password": "temporary-strong-password",
                "project_assignment_ids": [str(project.pk)],
                "is_active": True,
                "must_change_password": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        qa = User.objects.get(email="qa-project@example.com")
        self.assertTrue(
            QAProjectAssignment.objects.filter(qa=qa, dialer_campaign=project).exists()
        )
        self.assertEqual(response.json()["assigned_projects"][0]["id"], str(project.pk))

    def test_qa_project_assignment_rejects_another_branch(self):
        other_branch = Branch.objects.create(
            company=self.company, name="Lahore", code="lhe"
        )
        dialer = Dialer(
            branch=other_branch,
            name="Secondary",
            api_url="https://secondary.example.com/non_agent_api.php",
            api_username="api",
        )
        dialer.set_api_password("secret")
        dialer.set_webhook_secret("another-long-private-webhook-secret")
        dialer.save()
        project = DialerCampaign.objects.create(
            dialer=dialer,
            campaign="SUPPORT",
            project_name="Customer Support",
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("administration-user-list"),
            {
                "email": "invalid-project@example.com",
                "first_name": "Invalid",
                "last_name": "Reviewer",
                "role": User.Role.QA,
                "company": str(self.company.pk),
                "branch": str(self.branch.pk),
                "password": "temporary-strong-password",
                "project_assignment_ids": [str(project.pk)],
                "is_active": True,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            User.objects.filter(email="invalid-project@example.com").exists()
        )

    def test_updating_dialer_project_name_preserves_qa_access(self):
        dialer = Dialer(
            branch=self.branch,
            name="Stable mapping",
            api_url="https://dialer.example.com/non_agent_api.php",
            api_username="api",
        )
        dialer.set_api_password("secret")
        dialer.set_webhook_secret("a-long-private-webhook-secret")
        dialer.save()
        project = DialerCampaign.objects.create(
            dialer=dialer,
            campaign="SALES",
            project_name="Original Project",
        )
        qa = User.objects.create_user(
            email="stable-access@example.com",
            password="a-very-strong-password",
            first_name="Stable",
            last_name="Reviewer",
            role=User.Role.QA,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        assignment = QAProjectAssignment.objects.create(qa=qa, dialer_campaign=project)
        self.client.force_login(self.admin)
        response = self.client.patch(
            reverse("administration-dialer-detail", kwargs={"pk": dialer.pk}),
            {"campaigns": [{"campaign": "sales", "project_name": "Renamed Project"}]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertEqual(assignment.dialer_campaign_id, project.pk)
        project.refresh_from_db()
        self.assertEqual(project.project_name, "Renamed Project")

    def test_administration_summary_returns_operational_counts(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("administration-summary"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["companies"], 1)
        self.assertEqual(response.json()["branches"], 1)
