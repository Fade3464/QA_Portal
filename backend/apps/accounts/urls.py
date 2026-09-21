from django.urls import path

from .views import (
    AccountView,
    AppearanceView,
    LedTeamAvatarView,
    LedTeamListView,
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    ProfileAvatarView,
    session_view,
)

urlpatterns = [
    path("account/", AccountView.as_view(), name="account-detail"),
    path("account/appearance/", AppearanceView.as_view(), name="account-appearance"),
    path("account/avatar/", ProfileAvatarView.as_view(), name="account-avatar"),
    path("account/teams/", LedTeamListView.as_view(), name="account-teams"),
    path(
        "account/teams/<uuid:team_id>/avatar/",
        LedTeamAvatarView.as_view(),
        name="account-team-avatar",
    ),
    path("session/", session_view, name="auth-session"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]
