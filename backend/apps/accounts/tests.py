import io
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.tenancy.models import Branch, Company, Dialer, DialerCampaign, Team

from .models import AuthenticationEvent, User


class AuthenticationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Acme", slug="acme")
        self.branch = Branch.objects.create(
            company=self.company, name="Lahore", code="lahore"
        )
        self.user = User.objects.create_user(
            email="qa@example.com",
            password="a-very-strong-password",
            first_name="Amina",
            last_name="Khan",
            role=User.Role.QA,
            company=self.company,
            branch=self.branch,
        )
        self.client = Client(enforce_csrf_checks=True)

    def csrf(self):
        self.client.get(reverse("auth-session"))
        return self.client.cookies["qa_portal_csrf"].value

    def test_login_requires_csrf(self):
        response = self.client.post(
            reverse("auth-login"),
            {"email": self.user.email, "password": "a-very-strong-password"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_login_and_logout(self):
        token = self.csrf()
        response = self.client.post(
            reverse("auth-login"),
            {
                "email": self.user.email,
                "password": "a-very-strong-password",
                "remember": True,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["branch"]["code"], "lahore")
        self.assertTrue(
            AuthenticationEvent.objects.filter(
                event=AuthenticationEvent.Event.LOGIN_SUCCESS, user=self.user
            ).exists()
        )
        response = self.client.post(
            reverse("auth-logout"), HTTP_X_CSRFTOKEN=response.json()["csrfToken"]
        )
        self.assertEqual(response.status_code, 204)

    def test_temporary_password_must_be_changed_before_api_access(self):
        token = self.csrf()
        login_response = self.client.post(
            reverse("auth-login"),
            {"email": self.user.email, "password": "a-very-strong-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        rotated_token = login_response.json()["csrfToken"]
        blocked = self.client.get(reverse("dashboard-summary"))
        self.assertEqual(blocked.status_code, 403)
        changed = self.client.post(
            reverse("password-change"),
            {
                "current_password": "a-very-strong-password",
                "password": "another-very-strong-password",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=rotated_token,
        )
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.json()["user"]["must_change_password"])
        self.assertEqual(self.client.get(reverse("dashboard-summary")).status_code, 200)

    def test_invalid_login_is_generic(self):
        response = self.client.post(
            reverse("auth-login"),
            {"email": "missing@example.com", "password": "wrong-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.csrf(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("missing", str(response.json()).lower())

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_https_forwarded_by_the_edge_proxy_is_trusted(self):
        response = self.client.get(
            reverse("auth-session"), HTTP_X_FORWARDED_PROTO="https"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.is_secure())


class AccountSettingsTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media.name)
        self.media_override.enable()
        self.company = Company.objects.create(name="CallLens", slug="calllens")
        self.branch = Branch.objects.create(
            company=self.company, name="New York", code="new-york"
        )
        self.leader = User.objects.create_user(
            email="leader@example.com",
            password="a-very-strong-password",
            first_name="Mina",
            last_name="Cole",
            role=User.Role.TEAM_LEADER,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.qa = User.objects.create_user(
            email="qa-settings@example.com",
            password="a-very-strong-password",
            first_name="Ari",
            last_name="Lane",
            role=User.Role.QA,
            company=self.company,
            branch=self.branch,
            must_change_password=False,
        )
        self.team = Team.objects.create(
            branch=self.branch, name="North Star", team_leader=self.leader
        )
        self.client = Client()

    def tearDown(self):
        self.media_override.disable()
        self.media.cleanup()

    def test_account_is_read_only_and_includes_preferences_and_projects(self):
        dialer = Dialer.objects.create(
            branch=self.branch,
            name="Primary",
            api_url="https://dialer.example.com",
            api_username="api",
        )
        project = DialerCampaign.objects.create(
            dialer=dialer, campaign="RETENTION", project_name="Retention"
        )
        self.qa.qa_project_assignments.create(dialer_campaign=project)
        self.client.force_login(self.qa)
        response = self.client.get(reverse("account-detail"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["appearance"]["preset"], "calllens")
        self.assertEqual(response.json()["assigned_projects"][0]["name"], "Retention")
        self.assertEqual(self.client.patch(reverse("account-detail"), {}).status_code, 405)

    def test_appearance_is_whitelisted_and_persisted(self):
        self.client.force_login(self.qa)
        response = self.client.patch(
            reverse("account-appearance"),
            {"mode": "dark", "preset": "purple", "compact": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.qa.refresh_from_db()
        self.assertEqual(self.qa.appearance_mode, User.AppearanceMode.DARK)
        self.assertEqual(self.qa.appearance_preset, User.AppearancePreset.PURPLE)
        self.assertTrue(self.qa.appearance_compact)
        invalid = self.client.patch(
            reverse("account-appearance"),
            {"preset": "untrusted-css"},
            content_type="application/json",
        )
        self.assertEqual(invalid.status_code, 400)

    def test_profile_picture_is_normalized_and_can_be_removed(self):
        source = io.BytesIO()
        Image.new("RGB", (900, 500), color=(30, 120, 210)).save(source, "PNG")
        self.client.force_login(self.qa)
        response = self.client.post(
            reverse("account-avatar"),
            {"avatar": SimpleUploadedFile("portrait.png", source.getvalue(), "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        self.qa.refresh_from_db()
        self.assertTrue(self.qa.profile_picture.name.endswith(".webp"))
        with Image.open(self.qa.profile_picture.path) as image:
            self.assertEqual(image.size, (512, 512))
        self.assertEqual(self.client.get(reverse("account-avatar")).status_code, 200)
        self.assertEqual(self.client.delete(reverse("account-avatar")).status_code, 200)
        self.qa.refresh_from_db()
        self.assertFalse(self.qa.profile_picture)

    def test_only_the_owning_team_leader_can_change_team_avatar(self):
        self.client.force_login(self.leader)
        response = self.client.patch(
            reverse("account-team-avatar", kwargs={"team_id": self.team.pk}),
            {"avatar": "rocket_launch"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.avatar, "rocket_launch")

        self.client.force_login(self.qa)
        self.assertEqual(self.client.get(reverse("account-teams")).status_code, 403)
        self.assertEqual(
            self.client.patch(
                reverse("account-team-avatar", kwargs={"team_id": self.team.pk}),
                {"avatar": "groups"},
                content_type="application/json",
            ).status_code,
            403,
        )
