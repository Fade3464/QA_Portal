import uuid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    is_active = models.BooleanField(default=True)

    # One company per portal deployment can expose the shared Grafana sales
    # analytics workspace. Viewer credentials are encrypted at rest using the
    # same deployment key used for other external-service credentials.
    analytics_enabled = models.BooleanField(default=False, db_index=True)
    grafana_viewer_username = models.CharField(max_length=120, blank=True)
    grafana_viewer_password_ciphertext = models.TextField(blank=True, editable=False)
    grafana_user_id = models.PositiveIntegerField(null=True, blank=True, editable=False)
    grafana_synced_username = models.CharField(max_length=120, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"
        constraints = [
            models.UniqueConstraint(
                fields=["analytics_enabled"],
                condition=models.Q(analytics_enabled=True),
                name="single_analytics_company",
            )
        ]

    @staticmethod
    def _credential_fernet() -> Fernet:
        key = settings.DIALER_CREDENTIAL_KEY
        if not key:
            raise ImproperlyConfigured(
                "DIALER_CREDENTIAL_KEY is required to store Grafana credentials"
            )
        return Fernet(key.encode())

    def set_grafana_viewer_password(self, raw_password: str) -> None:
        self.grafana_viewer_password_ciphertext = (
            self._credential_fernet().encrypt(raw_password.encode()).decode()
        )

    def get_grafana_viewer_password(self) -> str:
        if not self.grafana_viewer_password_ciphertext:
            return ""
        try:
            return (
                self._credential_fernet()
                .decrypt(self.grafana_viewer_password_ciphertext.encode())
                .decode()
            )
        except (InvalidToken, ValueError) as exc:
            raise ValidationError(
                "The stored Grafana viewer credential cannot be decrypted."
            ) from exc

    @property
    def has_grafana_viewer_config(self) -> bool:
        return bool(
            self.analytics_enabled
            and self.grafana_viewer_username
            and self.grafana_viewer_password_ciphertext
        )

    def __str__(self) -> str:
        return self.name


class Branch(models.Model):
    TIMEZONE_CHOICES = (("America/New_York", "Eastern Time (New York)"),)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="branches"
    )
    name = models.CharField(max_length=160)
    code = models.SlugField(max_length=50)
    timezone = models.CharField(
        max_length=64,
        choices=TIMEZONE_CHOICES,
        default="America/New_York",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["company__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="unique_branch_code_per_company"
            )
        ]

    def __str__(self) -> str:
        return f"{self.company.name} · {self.name}"


class Team(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="teams")
    name = models.CharField(max_length=160)
    avatar = models.CharField(
        max_length=80,
        default="groups",
        validators=[
            RegexValidator(
                regex=r"^[a-z0-9_]+$",
                message="Choose a valid Material Symbol avatar.",
            )
        ],
    )
    team_leader = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="led_teams"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch__company__name", "branch__name", "name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "branch", name="unique_team_name_per_branch_ci"
            )
        ]

    def clean(self) -> None:
        super().clean()
        self.name = " ".join(self.name.split())
        if not self.branch_id or not self.team_leader_id:
            return
        if self.team_leader.branch_id != self.branch_id:
            raise ValidationError(
                {"team_leader": "The team leader must belong to the selected branch."}
            )
        if self.team_leader.role != self.team_leader.Role.TEAM_LEADER:
            raise ValidationError(
                {"team_leader": "The selected user must have the Team Leader role."}
            )

    def __str__(self) -> str:
        return f"{self.branch} · {self.name}"


class Dialer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="dialers")
    name = models.CharField(max_length=160)
    # Existing dialers are fronter dialers. Closer-to-fronter ownership is
    # stored in DialerFronterMapping so one closer can own many fronters while
    # each fronter can belong to at most one closer.
    is_closer = models.BooleanField(default=False, db_index=True)
    api_url = models.URLField(max_length=500)
    api_username = models.CharField(max_length=120)
    api_password_ciphertext = models.TextField(blank=True, editable=False)
    api_source = models.CharField(max_length=120, default="qa_portal")
    # Optional VICIdial User Stats credentials used only for resolving the
    # latest XFER_3WAY preset after a SALE disposition.
    preset_lookup_url = models.URLField(max_length=500, blank=True)
    preset_lookup_username = models.CharField(max_length=120, blank=True)
    preset_lookup_password_ciphertext = models.TextField(blank=True, editable=False)
    preset_lookup_verify_tls = models.BooleanField(default=True)
    webhook_secret_hash = models.CharField(max_length=256, blank=True, editable=False)
    request_timeout_seconds = models.PositiveSmallIntegerField(default=15)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch__company__name", "branch__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"], name="unique_dialer_name_per_branch"
            )
        ]

    def __str__(self) -> str:
        return f"{self.branch} · {self.name}"

    @staticmethod
    def _fernet() -> Fernet:
        key = settings.DIALER_CREDENTIAL_KEY
        if not key:
            raise ImproperlyConfigured(
                "DIALER_CREDENTIAL_KEY is required to store dialer credentials"
            )
        return Fernet(key.encode())

    def set_api_password(self, raw_password: str) -> None:
        self.api_password_ciphertext = (
            self._fernet().encrypt(raw_password.encode()).decode()
        )

    def get_api_password(self) -> str:
        try:
            return (
                self._fernet().decrypt(self.api_password_ciphertext.encode()).decode()
            )
        except (InvalidToken, ValueError) as exc:
            raise ValidationError(
                "The stored dialer credential cannot be decrypted."
            ) from exc

    def set_preset_lookup_password(self, raw_password: str) -> None:
        self.preset_lookup_password_ciphertext = (
            self._fernet().encrypt(raw_password.encode()).decode()
        )

    def get_preset_lookup_password(self) -> str:
        if not self.preset_lookup_password_ciphertext:
            return ""
        try:
            return (
                self._fernet()
                .decrypt(self.preset_lookup_password_ciphertext.encode())
                .decode()
            )
        except (InvalidToken, ValueError) as exc:
            raise ValidationError(
                "The stored preset lookup credential cannot be decrypted."
            ) from exc

    @property
    def has_preset_lookup_config(self) -> bool:
        return bool(
            self.preset_lookup_url
            and self.preset_lookup_username
            and self.preset_lookup_password_ciphertext
        )

    def set_webhook_secret(self, raw_secret: str) -> None:
        self.webhook_secret_hash = make_password(raw_secret)

    def check_webhook_secret(self, raw_secret: str) -> bool:
        return bool(
            raw_secret
            and self.webhook_secret_hash
            and check_password(raw_secret, self.webhook_secret_hash)
        )


class DialerFronterMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    closer_dialer = models.ForeignKey(
        Dialer,
        on_delete=models.CASCADE,
        related_name="fronter_mappings",
    )
    fronter_dialer = models.OneToOneField(
        Dialer,
        on_delete=models.PROTECT,
        related_name="closer_mapping",
    )
    ingroup_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["closer_dialer__name", "fronter_dialer__name"]

    @staticmethod
    def normalize_ingroup_names(value: str) -> tuple[str, list[str]]:
        raw_parts = (value or "").split(",")
        names = [" ".join(part.split()) for part in raw_parts]
        if not (value or "").strip() or any(not name for name in names):
            raise ValidationError(
                "Enter one or two in-group names separated by a comma."
            )
        if len(names) > 2:
            raise ValidationError(
                "A fronter mapping can contain at most two in-group names."
            )
        if len({name.casefold() for name in names}) != len(names):
            raise ValidationError("The same in-group name cannot be listed twice.")
        return ", ".join(names), names

    @property
    def ingroup_names(self) -> list[str]:
        try:
            _, names = self.normalize_ingroup_names(self.ingroup_name)
            return names
        except ValidationError:
            return []

    def clean(self) -> None:
        super().clean()
        errors = {}
        try:
            self.ingroup_name, _ = self.normalize_ingroup_names(self.ingroup_name)
        except ValidationError as exc:
            errors["ingroup_name"] = exc.messages
        if self.closer_dialer_id and not self.closer_dialer.is_closer:
            errors["closer_dialer"] = "Mappings can only belong to closer dialers."
        if self.fronter_dialer_id and self.fronter_dialer.is_closer:
            errors["fronter_dialer"] = "A closer dialer can only map fronter dialers."
        if self.closer_dialer_id and self.fronter_dialer_id:
            if self.closer_dialer_id == self.fronter_dialer_id:
                errors["fronter_dialer"] = "A closer dialer cannot map to itself."
            elif (
                self.closer_dialer.branch_id
                and self.fronter_dialer.branch_id
                and self.closer_dialer.branch.company_id
                != self.fronter_dialer.branch.company_id
            ):
                errors["fronter_dialer"] = (
                    "The fronter and closer dialers must belong to the same company."
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.closer_dialer.name} ← {self.fronter_dialer.name} ({self.ingroup_name})"


class DialerCampaign(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dialer = models.ForeignKey(
        Dialer, on_delete=models.CASCADE, related_name="campaigns"
    )
    campaign = models.CharField(max_length=120)
    project_name = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["dialer__name", "campaign"]
        constraints = [
            models.UniqueConstraint(
                Lower("campaign"), "dialer", name="unique_campaign_per_dialer_ci"
            )
        ]

    def clean(self) -> None:
        super().clean()
        self.campaign = " ".join(self.campaign.split())
        self.project_name = " ".join(self.project_name.split())
        if not self.campaign:
            raise ValidationError({"campaign": "Campaign is required."})
        if not self.project_name:
            raise ValidationError({"project_name": "Project name is required."})

    def __str__(self) -> str:
        return f"{self.dialer.name} · {self.campaign} → {self.project_name}"


class QAProjectAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    qa = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="qa_project_assignments",
    )
    dialer_campaign = models.ForeignKey(
        DialerCampaign,
        on_delete=models.CASCADE,
        related_name="qa_assignments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [
            "qa__first_name",
            "qa__last_name",
            "dialer_campaign__dialer__name",
            "dialer_campaign__project_name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["qa", "dialer_campaign"],
                name="unique_qa_project_assignment",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if not self.qa_id or not self.dialer_campaign_id:
            return
        if self.qa.role not in {
            self.qa.Role.QA,
            self.qa.Role.TEAM_LEADER,
            self.qa.Role.PROJECT_MANAGER,
            self.qa.Role.DIALER_MANAGER,
        }:
            raise ValidationError(
                {
                    "qa": (
                        "Project access can only be assigned to QA, Team Leader, "
                        "Project Manager, or Dialer Manager users."
                    )
                }
            )
        if self.qa.role == self.qa.Role.DIALER_MANAGER:
            if self.qa.company_id != self.dialer_campaign.dialer.branch.company_id:
                raise ValidationError(
                    {
                        "dialer_campaign": (
                            "A Dialer Manager can only be assigned projects from their company."
                        )
                    }
                )
        elif self.qa.branch_id != self.dialer_campaign.dialer.branch_id:
            raise ValidationError(
                {
                    "dialer_campaign": (
                        "The project must belong to a dialer in the user's branch."
                    )
                }
            )

    def __str__(self) -> str:
        return f"{self.qa.full_name} · {self.dialer_campaign}"
