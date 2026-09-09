from django.db.models import Count
from rest_framework import mixins, permissions, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AuthenticationEvent, User
from apps.calls.models import CallEvent

from .api_serializers import (
    AuthenticationEventAdminSerializer,
    BranchAdminSerializer,
    CompanyAdminSerializer,
    DialerAdminSerializer,
    TeamAdminSerializer,
    UserAdminSerializer,
)
from .models import Branch, Company, Dialer, Team


class IsSystemAdministrator(permissions.BasePermission):
    message = "System administrator access is required."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.is_active
            and request.user.is_superuser
        )


class ManagedModelViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsSystemAdministrator]


class CompanyViewSet(ManagedModelViewSet):
    serializer_class = CompanyAdminSerializer
    queryset = Company.objects.annotate(
        branches_count=Count("branches", distinct=True),
        users_count=Count("users", distinct=True),
    )


class BranchViewSet(ManagedModelViewSet):
    serializer_class = BranchAdminSerializer
    queryset = Branch.objects.select_related("company").annotate(
        users_count=Count("users", distinct=True),
        dialers_count=Count("dialers", distinct=True),
    )


class DialerViewSet(ManagedModelViewSet):
    serializer_class = DialerAdminSerializer
    queryset = Dialer.objects.select_related(
        "branch", "branch__company"
    ).prefetch_related("campaigns")


class TeamViewSet(ManagedModelViewSet):
    serializer_class = TeamAdminSerializer
    queryset = Team.objects.select_related(
        "branch", "branch__company", "team_leader"
    ).annotate(calls_count=Count("call_events", distinct=True))


class UserViewSet(ManagedModelViewSet):
    serializer_class = UserAdminSerializer
    queryset = (
        User.objects.filter(is_superuser=False)
        .select_related("company", "branch")
        .prefetch_related("qa_project_assignments__dialer_campaign__dialer")
    )


class AuthenticationEventViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = AuthenticationEventAdminSerializer
    permission_classes = [IsSystemAdministrator]
    queryset = AuthenticationEvent.objects.select_related("user")[:250]


class AdministrationSummaryView(APIView):
    permission_classes = [IsSystemAdministrator]

    def get(self, request):
        return Response(
            {
                "companies": Company.objects.count(),
                "branches": Branch.objects.count(),
                "teams": Team.objects.count(),
                "active_teams": Team.objects.filter(is_active=True).count(),
                "users": User.objects.filter(is_superuser=False).count(),
                "active_users": User.objects.filter(
                    is_superuser=False, is_active=True
                ).count(),
                "dialers": Dialer.objects.count(),
                "active_dialers": Dialer.objects.filter(is_active=True).count(),
                "calls": CallEvent.objects.count(),
                "recent_security_events": AuthenticationEventAdminSerializer(
                    AuthenticationEvent.objects.select_related("user")[:6], many=True
                ).data,
            }
        )
