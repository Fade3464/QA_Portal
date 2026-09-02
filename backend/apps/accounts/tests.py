from django.test import Client, TestCase
from django.urls import reverse

from apps.tenancy.models import Branch, Company

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
