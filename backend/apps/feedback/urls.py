from django.urls import path

from .views import (
    FeedbackAdminDetailView,
    FeedbackAdminListView,
    FeedbackImageView,
    FeedbackSubmitView,
)

urlpatterns = [
    path("", FeedbackSubmitView.as_view(), name="feedback-submit"),
    path("admin/", FeedbackAdminListView.as_view(), name="feedback-admin-list"),
    path(
        "admin/<uuid:pk>/",
        FeedbackAdminDetailView.as_view(),
        name="feedback-admin-detail",
    ),
    path(
        "<uuid:feedback_id>/images/<uuid:image_id>/",
        FeedbackImageView.as_view(),
        name="feedback-image",
    ),
]
