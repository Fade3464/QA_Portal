from django import forms
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured

from .models import Branch, Company, Dialer


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "code", "timezone", "is_active")
    list_filter = ("company", "is_active")
    search_fields = ("name", "code", "company__name")


class DialerAdminForm(forms.ModelForm):
    api_url = forms.URLField(assume_scheme="https")
    api_password = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        help_text="Leave blank to keep the current value.",
    )
    webhook_secret = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        help_text="Use a long random value; it is shown only while you enter it.",
    )

    class Meta:
        model = Dialer
        exclude = ("api_password_ciphertext", "webhook_secret_hash")

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("api_password"):
            self.add_error(
                "api_password", "An API password is required for a new dialer."
            )
        if not self.instance.pk and not cleaned.get("webhook_secret"):
            self.add_error(
                "webhook_secret", "A webhook secret is required for a new dialer."
            )
        if cleaned.get("api_password"):
            try:
                Dialer._fernet()
            except (ImproperlyConfigured, ValueError) as exc:
                self.add_error("api_password", str(exc))
        return cleaned

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("api_password"):
            instance.set_api_password(self.cleaned_data["api_password"])
        if self.cleaned_data.get("webhook_secret"):
            instance.set_webhook_secret(self.cleaned_data["webhook_secret"])
        if commit:
            instance.save()
        return instance


@admin.register(Dialer)
class DialerAdmin(admin.ModelAdmin):
    form = DialerAdminForm
    list_display = ("name", "branch", "api_url", "is_active", "updated_at")
    list_filter = ("branch__company", "branch", "is_active")
    search_fields = ("name", "branch__name", "branch__company__name", "api_url")
    readonly_fields = ("id", "created_at", "updated_at")
