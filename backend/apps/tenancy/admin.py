from django import forms
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured

from .models import Branch, Company, Dialer, DialerCampaign, QAProjectAssignment, Team


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


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "avatar",
        "branch",
        "team_leader",
        "is_active",
        "updated_at",
    )
    list_filter = ("branch__company", "branch", "is_active")
    search_fields = ("name", "branch__name", "team_leader__email")
    autocomplete_fields = ("team_leader",)


class DialerAdminForm(forms.ModelForm):
    api_url = forms.URLField(assume_scheme="https")
    api_password = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        help_text="Leave blank to keep the current value.",
    )
    preset_lookup_password = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        help_text="Leave blank to keep the current User Stats credential.",
    )
    webhook_secret = forms.CharField(
        widget=forms.PasswordInput,
        required=False,
        help_text="Use a long random value; it is shown only while you enter it.",
    )

    class Meta:
        model = Dialer
        exclude = (
            "api_password_ciphertext",
            "preset_lookup_password_ciphertext",
            "webhook_secret_hash",
        )

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
        lookup_url = cleaned.get("preset_lookup_url")
        lookup_username = cleaned.get("preset_lookup_username")
        lookup_password = cleaned.get("preset_lookup_password")
        existing_lookup_password = bool(
            self.instance.pk and self.instance.preset_lookup_password_ciphertext
        )
        if lookup_url or lookup_username or lookup_password or existing_lookup_password:
            if not lookup_url:
                self.add_error("preset_lookup_url", "User Stats URL is required.")
            if not lookup_username:
                self.add_error("preset_lookup_username", "User Stats username is required.")
            if not lookup_password and not existing_lookup_password:
                self.add_error("preset_lookup_password", "User Stats password is required.")
        if cleaned.get("api_password") or lookup_password:
            try:
                Dialer._fernet()
            except (ImproperlyConfigured, ValueError) as exc:
                self.add_error("api_password", str(exc))
        return cleaned

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("api_password"):
            instance.set_api_password(self.cleaned_data["api_password"])
        if self.cleaned_data.get("preset_lookup_password"):
            instance.set_preset_lookup_password(self.cleaned_data["preset_lookup_password"])
        if self.cleaned_data.get("webhook_secret"):
            instance.set_webhook_secret(self.cleaned_data["webhook_secret"])
        if commit:
            instance.save()
        return instance


class DialerCampaignInline(admin.TabularInline):
    model = DialerCampaign
    extra = 1
    fields = ("campaign", "project_name")


@admin.register(DialerCampaign)
class DialerCampaignAdmin(admin.ModelAdmin):
    list_display = ("campaign", "project_name", "dialer")
    list_filter = ("dialer__branch__company", "dialer__branch", "dialer")
    search_fields = (
        "campaign",
        "project_name",
        "dialer__name",
        "dialer__branch__name",
    )


@admin.register(QAProjectAssignment)
class QAProjectAssignmentAdmin(admin.ModelAdmin):
    list_display = ("qa", "dialer_campaign", "created_at")
    list_filter = (
        "dialer_campaign__dialer__branch__company",
        "dialer_campaign__dialer__branch",
        "dialer_campaign__dialer",
    )
    search_fields = (
        "qa__email",
        "qa__first_name",
        "qa__last_name",
        "dialer_campaign__campaign",
        "dialer_campaign__project_name",
    )
    autocomplete_fields = ("qa", "dialer_campaign")


@admin.register(Dialer)
class DialerAdmin(admin.ModelAdmin):
    form = DialerAdminForm
    list_display = ("name", "branch", "api_url", "is_active", "updated_at")
    list_filter = ("branch__company", "branch", "is_active")
    search_fields = ("name", "branch__name", "branch__company__name", "api_url")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = (DialerCampaignInline,)
