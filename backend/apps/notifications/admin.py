from django.contrib import admin

from .models import SystemNotification


@admin.register(SystemNotification)
class SystemNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "severity",
        "branch",
        "occurrences",
        "resolved_at",
        "updated_at",
    )
    list_filter = ("category", "severity", "resolved_at", "branch__company")
    search_fields = ("title", "message", "dedupe_key")
    readonly_fields = (
        "id",
        "dedupe_key",
        "occurrences",
        "created_at",
        "updated_at",
    )
