from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AuthenticationEvent, User
from .serializers import (
    CurrentUserSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
)
from .throttles import LoginThrottle, PasswordResetThrottle


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (
        forwarded.split(",", 1)[0].strip()
        if forwarded
        else request.META.get("REMOTE_ADDR")
    ) or None


def audit(request, event: str, *, user=None, email: str = "") -> None:
    AuthenticationEvent.objects.create(
        user=user,
        email=(email or getattr(user, "email", "")).lower(),
        event=event,
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )


@ensure_csrf_cookie
def session_view(request):
    payload = {
        "authenticated": request.user.is_authenticated,
        "csrfToken": get_token(request),
    }
    if request.user.is_authenticated:
        payload["user"] = CurrentUserSerializer(request.user).data
    return JsonResponse(payload)


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        user = authenticate(
            request=request,
            username=email,
            password=serializer.validated_data["password"],
        )
        if user is None or not user.is_active:
            audit(request, AuthenticationEvent.Event.LOGIN_FAILURE, email=email)
            return Response(
                {
                    "error": {
                        "status": 400,
                        "detail": "The email or password is incorrect.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        login(request, user)
        request.session.set_expiry(
            settings.SESSION_COOKIE_AGE if serializer.validated_data["remember"] else 0
        )
        request.session["auth_time"] = timezone.now().isoformat()
        audit(request, AuthenticationEvent.Event.LOGIN_SUCCESS, user=user)
        return Response(
            {"user": CurrentUserSerializer(user).data, "csrfToken": get_token(request)}
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        audit(request, AuthenticationEvent.Event.LOGOUT, user=user)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        user = User.objects.filter(email=email, is_active=True).first()
        audit(
            request,
            AuthenticationEvent.Event.PASSWORD_RESET_REQUEST,
            user=user,
            email=email,
        )
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?uid={uid}&token={token}"
            send_mail(
                "Reset your QA Portal password",
                f"Use this secure link to reset your password:\n\n{reset_url}\n\nIf you did not request this, ignore this email.",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
            )
        return Response(
            {
                "detail": "If that account exists, password reset instructions have been sent."
            }
        )


@method_decorator(csrf_protect, name="dispatch")
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user_id = force_str(urlsafe_base64_decode(serializer.validated_data["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            user = None
        if user is None or not default_token_generator.check_token(
            user, serializer.validated_data["token"]
        ):
            return Response(
                {
                    "error": {
                        "status": 400,
                        "detail": "This reset link is invalid or has expired.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(serializer.validated_data["password"], user=user)
        except DjangoValidationError as exc:
            return Response(
                {"error": {"status": 400, "detail": list(exc.messages)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            user.set_password(serializer.validated_data["password"])
            user.must_change_password = False
            user.last_password_change = timezone.now()
            user.save(
                update_fields=[
                    "password",
                    "must_change_password",
                    "last_password_change",
                    "updated_at",
                ]
            )
            user.session_set.all().delete()
            audit(request, AuthenticationEvent.Event.PASSWORD_RESET, user=user)
        return Response(
            {"detail": "Your password has been reset. You can now sign in."}
        )


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data["current_password"]):
            return Response(
                {
                    "error": {
                        "status": 400,
                        "detail": "Your current password is incorrect.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(serializer.validated_data["password"], user=user)
        except DjangoValidationError as exc:
            return Response(
                {"error": {"status": 400, "detail": list(exc.messages)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(serializer.validated_data["password"])
        user.must_change_password = False
        user.last_password_change = timezone.now()
        user.save(
            update_fields=[
                "password",
                "must_change_password",
                "last_password_change",
                "updated_at",
            ]
        )
        update_session_auth_hash(request, user)
        audit(request, AuthenticationEvent.Event.PASSWORD_CHANGE, user=user)
        return Response(
            {"user": CurrentUserSerializer(user).data, "csrfToken": get_token(request)}
        )
