from django.contrib import admin

from .models import Feedback, FeedbackImage


class FeedbackImageInline(admin.TabularInline):
    model = FeedbackImage
    extra = 0
    readonly_fields = ("id", "image", "original_name", "created_at")


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "reviewed_by", "created_at", "reviewed_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "message")
    readonly_fields = ("id", "user", "message", "created_at", "updated_at")
    inlines = [FeedbackImageInline]
