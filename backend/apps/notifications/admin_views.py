from uuid import UUID

from django.db.models import Count
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.tenancy.models import Branch, Company

from .models import SystemNotification
from .services import queue_custom_notification


class IsSystemAdministrator(BasePermission):
    message = "System administrator access is required."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.is_active
            and request.user.is_superuser
        )


class CustomNotificationInputSerializer(serializers.Serializer):
    class Audience:
        ALL = "all"
        USERS = "users"
        ROLES = "roles"
        COMPANIES = "companies"
        BRANCHES = "branches"

    audience = serializers.ChoiceField(
        choices=(
            (Audience.ALL, "Everyone"),
            (Audience.USERS, "Selected users"),
            (Audience.ROLES, "User roles"),
            (Audience.COMPANIES, "Companies"),
            (Audience.BRANCHES, "Branches"),
        )
    )
    target_ids = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, default=list
    )
    severity = serializers.ChoiceField(choices=SystemNotification.Severity.choices)
    title = serializers.CharField(max_length=120, trim_whitespace=True)
    message = serializers.CharField(max_length=1000, trim_whitespace=True)

    def validate(self, attrs):
        audience = attrs["audience"]
        target_ids = list(dict.fromkeys(attrs.get("target_ids", [])))
        if audience == self.Audience.ALL and target_ids:
            raise serializers.ValidationError(
                {"target_ids": "Everyone does not accept individual targets."}
            )
        if audience != self.Audience.ALL and not target_ids:
            raise serializers.ValidationError(
                {"target_ids": "Choose at least one audience target."}
            )
        if audience in {
            self.Audience.USERS,
            self.Audience.COMPANIES,
            self.Audience.BRANCHES,
        }:
            try:
                target_ids = [str(UUID(value)) for value in target_ids]
            except (TypeError, ValueError, AttributeError) as exc:
                raise serializers.ValidationError(
                    {"target_ids": "One or more audience targets are invalid."}
                ) from exc
        if audience == self.Audience.ROLES:
            allowed_roles = {
                User.Role.QA,
                User.Role.TEAM_LEADER,
                User.Role.PROJECT_MANAGER,
                User.Role.SUPERVISOR,
            }
            invalid_roles = set(target_ids) - allowed_roles
            if invalid_roles:
                raise serializers.ValidationError(
                    {"target_ids": "One or more user roles are invalid."}
                )
        attrs["target_ids"] = target_ids
        return attrs


def _audience_label(labels):
    labels = list(labels)
    if len(labels) <= 3:
        return ", ".join(labels)
    return f"{', '.join(labels[:3])} +{len(labels) - 3} more"


def _resolve_recipients(audience, target_ids):
    base = User.objects.filter(is_active=True, is_superuser=False).select_related(
        "company", "branch"
    )
    if audience == CustomNotificationInputSerializer.Audience.ALL:
        return list(base), "All active portal users"
    if audience == CustomNotificationInputSerializer.Audience.USERS:
        recipients = list(base.filter(pk__in=target_ids))
        if len(recipients) != len(target_ids):
            raise serializers.ValidationError(
                {"target_ids": "One or more selected users are unavailable."}
            )
        return recipients, _audience_label(user.full_name for user in recipients)
    if audience == CustomNotificationInputSerializer.Audience.ROLES:
        recipients = list(base.filter(role__in=target_ids))
        labels = [dict(User.Role.choices)[role] for role in target_ids]
        return recipients, _audience_label(labels)
    if audience == CustomNotificationInputSerializer.Audience.COMPANIES:
        companies = list(Company.objects.filter(pk__in=target_ids).order_by("name"))
        if len(companies) != len(target_ids):
            raise serializers.ValidationError(
                {"target_ids": "One or more selected companies no longer exist."}
            )
        return list(base.filter(company_id__in=target_ids)), _audience_label(
            company.name for company in companies
        )
    branches = list(
        Branch.objects.filter(pk__in=target_ids)
        .select_related("company")
        .order_by("company__name", "name")
    )
    if len(branches) != len(target_ids):
        raise serializers.ValidationError(
            {"target_ids": "One or more selected branches no longer exist."}
        )
    return list(base.filter(branch_id__in=target_ids)), _audience_label(
        f"{branch.company.name} · {branch.name}" for branch in branches
    )


def _serialize_broadcast(notification):
    recipient_count = getattr(notification, "recipient_count", None)
    read_count = getattr(notification, "read_count", None)
    if recipient_count is None:
        recipient_count = notification.recipients.count()
    if read_count is None:
        read_count = notification.read_by.count()
    return {
        "id": str(notification.pk),
        "title": notification.title,
        "message": notification.message,
        "severity": notification.severity,
        "audience": notification.metadata.get("audience_type", ""),
        "audience_label": notification.metadata.get("audience_label", ""),
        "sender_name": notification.metadata.get("sender_name", "System Administrator"),
        "recipient_count": recipient_count,
        "read_count": read_count,
        "created_at": notification.created_at.isoformat(),
    }


class CustomNotificationAdminView(APIView):
    permission_classes = [IsSystemAdministrator]

    def get(self, request):
        notifications = (
            SystemNotification.objects.filter(
                category=SystemNotification.Category.CUSTOM
            )
            .annotate(
                recipient_count=Count("recipients", distinct=True),
                read_count=Count("read_by", distinct=True),
            )
            .order_by("-created_at")[:100]
        )
        return Response(
            {"results": [_serialize_broadcast(item) for item in notifications]}
        )

    def post(self, request):
        serializer = CustomNotificationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        recipients, audience_label = _resolve_recipients(
            payload["audience"], payload["target_ids"]
        )
        if not recipients:
            raise serializers.ValidationError(
                {"audience": "The selected audience has no active users."}
            )
        notification = queue_custom_notification(
            sender=request.user,
            title=payload["title"],
            message=payload["message"],
            severity=payload["severity"],
            recipients=recipients,
            audience_type=payload["audience"],
            audience_label=audience_label,
            target_ids=payload["target_ids"],
        )
        return Response(
            _serialize_broadcast(notification), status=status.HTTP_201_CREATED
        )
