import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .managers import UserManager


class User(AbstractUser):
    class Role(models.TextChoices):
        QA = "qa", "QA Analyst"
        TEAM_LEADER = "team_leader", "Team Leader"
        PROJECT_MANAGER = "project_manager", "Project Manager"
        SUPERVISOR = "supervisor", "Supervisor"
        ADMINISTRATOR = "administrator", "System Administrator"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = None
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    role = models.CharField(max_length=32, choices=Role.choices)
    company = models.ForeignKey(
        "tenancy.Company",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    must_change_password = models.BooleanField(default=True)
    last_password_change = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]
    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name", "email"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(is_superuser=True, company__isnull=True, branch__isnull=True)
                    | Q(is_superuser=False, company__isnull=False, branch__isnull=False)
                ),
                name="user_tenant_required_unless_superuser",
            )
        ]

    def clean(self) -> None:
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email).lower()
        if self.is_superuser:
            if self.role != self.Role.ADMINISTRATOR:
                raise ValidationError(
                    {"role": "A superuser must have the Administrator role."}
                )
            return
        if not self.company_id or not self.branch_id:
            raise ValidationError(
                "Every portal user must belong to a company and branch."
            )
        if self.branch.company_id != self.company_id:
            raise ValidationError(
                {"branch": "The selected branch must belong to the selected company."}
            )
        if self.role == self.Role.ADMINISTRATOR:
            raise ValidationError(
                {"role": "The Administrator role is reserved for system superusers."}
            )

    @property
    def full_name(self) -> str:
        return self.get_full_name() or self.email


class AuthenticationEvent(models.Model):
    class Event(models.TextChoices):
        LOGIN_SUCCESS = "login_success", "Login success"
        LOGIN_FAILURE = "login_failure", "Login failure"
        LOGOUT = "logout", "Logout"
        PASSWORD_RESET_REQUEST = "password_reset_request", "Password reset requested"
        PASSWORD_RESET = "password_reset", "Password reset"
        PASSWORD_CHANGE = "password_change", "Password changed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authentication_events",
    )
    email = models.EmailField(blank=True)
    event = models.CharField(max_length=40, choices=Event.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "created_at"]),
            models.Index(fields=["event", "created_at"]),
        ]
