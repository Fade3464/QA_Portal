from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeForm, UserCreationForm
from .models import AuthenticationEvent, User
from apps.tenancy.models import QAProjectAssignment


class QAProjectAssignmentInline(admin.TabularInline):
    model = QAProjectAssignment
    extra = 0
    autocomplete_fields = ("dialer_campaign",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    ordering = ("email",)
    list_display = (
        "email",
        "first_name",
        "last_name",
        "role",
        "company",
        "branch",
        "is_active",
    )
    list_filter = ("role", "company", "branch", "is_active", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    readonly_fields = (
        "last_login",
        "date_joined",
        "created_at",
        "updated_at",
        "last_password_change",
    )
    inlines = (QAProjectAssignmentInline,)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Identity",
            {"fields": ("first_name", "last_name", "role", "company", "branch")},
        ),
        (
            "Security",
            {
                "fields": (
                    "is_active",
                    "must_change_password",
                    "last_password_change",
                    "last_login",
                )
            },
        ),
        (
            "Permissions",
            {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "role",
                    "company",
                    "branch",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )


@admin.register(AuthenticationEvent)
class AuthenticationEventAdmin(admin.ModelAdmin):
    list_display = ("event", "email", "ip_address", "created_at")
    list_filter = ("event", "created_at")
    search_fields = ("email", "ip_address", "user_agent")
    readonly_fields = (
        "user",
        "email",
        "event",
        "ip_address",
        "user_agent",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
