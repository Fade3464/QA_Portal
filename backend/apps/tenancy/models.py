import uuid

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return self.name


class Branch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="branches"
    )
    name = models.CharField(max_length=160)
    code = models.SlugField(max_length=50)
    timezone = models.CharField(max_length=64, default="Asia/Karachi")
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


class Dialer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="dialers")
    name = models.CharField(max_length=160)
    api_url = models.URLField(max_length=500)
    api_username = models.CharField(max_length=120)
    api_password_ciphertext = models.TextField(blank=True, editable=False)
    api_source = models.CharField(max_length=120, default="qa_portal")
    webhook_secret_hash = models.CharField(max_length=256, blank=True, editable=False)
    allowed_recording_hosts = models.TextField(
        blank=True,
        help_text="Comma-separated hostnames permitted for recording downloads.",
    )
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

    def set_webhook_secret(self, raw_secret: str) -> None:
        self.webhook_secret_hash = make_password(raw_secret)

    def check_webhook_secret(self, raw_secret: str) -> bool:
        return bool(
            raw_secret
            and self.webhook_secret_hash
            and check_password(raw_secret, self.webhook_secret_hash)
        )

    @property
    def recording_hosts(self) -> set[str]:
        return {
            host.strip().lower()
            for host in self.allowed_recording_hosts.split(",")
            if host.strip()
        }
