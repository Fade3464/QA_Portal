from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import AuthenticationEvent, User

from .models import (
    Branch,
    Company,
    Dialer,
    DialerCampaign,
    QAProjectAssignment,
    Team,
)


class CompanyAdminSerializer(serializers.ModelSerializer):
    branches_count = serializers.IntegerField(read_only=True)
    users_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Company
        fields = (
            "id",
            "name",
            "slug",
            "is_active",
            "branches_count",
            "users_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class BranchAdminSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    users_count = serializers.IntegerField(read_only=True)
    dialers_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Branch
        fields = (
            "id",
            "company",
            "company_name",
            "name",
            "code",
            "timezone",
            "is_active",
            "users_count",
            "dialers_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class TeamAdminSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    company_name = serializers.CharField(source="branch.company.name", read_only=True)
    team_leader_name = serializers.CharField(
        source="team_leader.full_name", read_only=True
    )
    team_leader_email = serializers.EmailField(
        source="team_leader.email", read_only=True
    )
    calls_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Team
        fields = (
            "id",
            "branch",
            "branch_name",
            "company_name",
            "name",
            "avatar",
            "team_leader",
            "team_leader_name",
            "team_leader_email",
            "is_active",
            "calls_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "calls_count", "created_at", "updated_at")

    def validate(self, attrs):
        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        leader = attrs.get("team_leader", getattr(self.instance, "team_leader", None))
        name = " ".join(attrs.get("name", getattr(self.instance, "name", "")).split())
        if not branch or not leader:
            raise serializers.ValidationError("A branch and team leader are required.")
        if leader.branch_id != branch.id:
            raise serializers.ValidationError(
                {"team_leader": "The team leader must belong to the selected branch."}
            )
        if leader.role != User.Role.TEAM_LEADER:
            raise serializers.ValidationError(
                {"team_leader": "The selected user must have the Team Leader role."}
            )
        duplicate = Team.objects.filter(branch=branch, name__iexact=name)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
            if (
                branch.id != self.instance.branch_id
                and self.instance.call_events.exists()
            ):
                raise serializers.ValidationError(
                    {
                        "branch": "A team with assigned calls cannot move to another branch."
                    }
                )
        if duplicate.exists():
            raise serializers.ValidationError(
                {"name": "A team with this name already exists in the branch."}
            )
        attrs["name"] = name
        return attrs

    @staticmethod
    def _assign_waiting_calls(team):
        from apps.calls.models import CallEvent
        from apps.notifications.services import resolve_unknown_team_notifications
        from django.db.models import Q

        prefixes = Q(team_name__iexact=team.name)
        leader_is_unambiguous = (
            not Team.objects.filter(
                branch=team.branch,
                team_leader=team.team_leader,
                is_active=True,
            )
            .exclude(pk=team.pk)
            .exists()
        )
        notification_aliases = []
        if team.is_active and leader_is_unambiguous:
            prefixes |= Q(team_name__iexact=team.team_leader.full_name)
            notification_aliases.append(team.team_leader.full_name)
        assigned = (
            CallEvent.objects.filter(
                branch=team.branch,
                team__isnull=True,
            )
            .filter(prefixes)
            .update(team=team)
        )
        resolve_unknown_team_notifications(team, aliases=notification_aliases)
        return assigned

    def create(self, validated_data):
        with transaction.atomic():
            team = Team(**validated_data)
            team.full_clean()
            team.save()
            self._assign_waiting_calls(team)
        return team

    def update(self, instance, validated_data):
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.full_clean()
            instance.save()
            self._assign_waiting_calls(instance)
        return instance


class DialerCampaignAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = DialerCampaign
        fields = ("id", "campaign", "project_name")
        read_only_fields = ("id",)


class DialerAdminSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    company_name = serializers.CharField(source="branch.company.name", read_only=True)
    api_password = serializers.CharField(
        write_only=True, required=False, allow_blank=False
    )
    webhook_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=False
    )
    webhook_path = serializers.SerializerMethodField()
    campaigns = DialerCampaignAdminSerializer(many=True, required=False)

    class Meta:
        model = Dialer
        fields = (
            "id",
            "branch",
            "branch_name",
            "company_name",
            "name",
            "api_url",
            "api_username",
            "api_password",
            "api_source",
            "webhook_secret",
            "webhook_path",
            "campaigns",
            "request_timeout_seconds",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "webhook_path", "created_at", "updated_at")

    def get_webhook_path(self, obj):
        return f"/api/v1/webhooks/vicidial/{obj.id}/dispo/"

    def validate(self, attrs):
        if not self.instance:
            if not attrs.get("api_password"):
                raise serializers.ValidationError(
                    {"api_password": "An API password is required."}
                )
            if not attrs.get("webhook_secret"):
                raise serializers.ValidationError(
                    {"webhook_secret": "A webhook secret is required."}
                )
        campaigns = attrs.get("campaigns")
        if campaigns is not None:
            seen = set()
            for mapping in campaigns:
                campaign = " ".join(mapping["campaign"].split())
                project_name = " ".join(mapping["project_name"].split())
                if not campaign:
                    raise serializers.ValidationError(
                        {"campaigns": "Every campaign code is required."}
                    )
                if not project_name:
                    raise serializers.ValidationError(
                        {"campaigns": "Every campaign must have a project name."}
                    )
                key = campaign.casefold()
                if key in seen:
                    raise serializers.ValidationError(
                        {"campaigns": f"Campaign {campaign} is listed more than once."}
                    )
                seen.add(key)
                mapping["campaign"] = campaign
                mapping["project_name"] = project_name
        return attrs

    @staticmethod
    def _replace_campaigns(dialer, campaigns):
        existing = {item.campaign.casefold(): item for item in dialer.campaigns.all()}
        retained_ids = []
        for mapping in campaigns:
            current = existing.get(mapping["campaign"].casefold())
            if current:
                current.campaign = mapping["campaign"]
                current.project_name = mapping["project_name"]
                current.full_clean()
                current.save(update_fields=["campaign", "project_name", "updated_at"])
            else:
                current = DialerCampaign(dialer=dialer, **mapping)
                current.full_clean()
                current.save()
            retained_ids.append(current.pk)
        dialer.campaigns.exclude(pk__in=retained_ids).delete()

    def create(self, validated_data):
        campaigns = validated_data.pop("campaigns", [])
        api_password = validated_data.pop("api_password")
        webhook_secret = validated_data.pop("webhook_secret")
        with transaction.atomic():
            dialer = Dialer(**validated_data)
            dialer.set_api_password(api_password)
            dialer.set_webhook_secret(webhook_secret)
            dialer.full_clean()
            dialer.save()
            self._replace_campaigns(dialer, campaigns)
        return dialer

    def update(self, instance, validated_data):
        campaigns = validated_data.pop("campaigns", None)
        api_password = validated_data.pop("api_password", "")
        webhook_secret = validated_data.pop("webhook_secret", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if api_password:
            instance.set_api_password(api_password)
        if webhook_secret:
            instance.set_webhook_secret(webhook_secret)
        with transaction.atomic():
            instance.full_clean()
            instance.save()
            if campaigns is not None:
                self._replace_campaigns(instance, campaigns)
        return instance


class UserAdminSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="full_name", read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    project_assignment_ids = serializers.PrimaryKeyRelatedField(
        queryset=DialerCampaign.objects.select_related("dialer", "dialer__branch"),
        many=True,
        required=False,
        write_only=True,
    )
    assigned_projects = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "name",
            "role",
            "role_label",
            "company",
            "company_name",
            "branch",
            "branch_name",
            "password",
            "project_assignment_ids",
            "assigned_projects",
            "is_active",
            "must_change_password",
            "last_login",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "last_login", "created_at", "updated_at")

    def validate_role(self, value):
        if value == User.Role.ADMINISTRATOR:
            raise serializers.ValidationError(
                "System administrators are created through the server console."
            )
        return value

    def validate(self, attrs):
        company = attrs.get("company", getattr(self.instance, "company", None))
        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        if not company or not branch:
            raise serializers.ValidationError("A company and branch are required.")
        if branch.company_id != company.id:
            raise serializers.ValidationError(
                {"branch": "The branch must belong to the selected company."}
            )
        role = attrs.get("role", getattr(self.instance, "role", None))
        assignments = attrs.get("project_assignment_ids")
        if assignments is None and self.instance:
            assignments = [
                assignment.dialer_campaign
                for assignment in self.instance.qa_project_assignments.select_related(
                    "dialer_campaign__dialer"
                )
            ]
        assignments = assignments or []
        if role == User.Role.QA:
            if not assignments:
                raise serializers.ValidationError(
                    {
                        "project_assignment_ids": "Assign at least one dialer project to every QA user."
                    }
                )
            invalid = [
                assignment
                for assignment in assignments
                if assignment.dialer.branch_id != branch.id
            ]
            if invalid:
                raise serializers.ValidationError(
                    {
                        "project_assignment_ids": (
                            "Every assigned project must belong to a dialer in the selected branch."
                        )
                    }
                )
        elif attrs.get("project_assignment_ids"):
            raise serializers.ValidationError(
                {
                    "project_assignment_ids": "Project access can only be assigned to QA users."
                }
            )
        if self.instance and self.instance.led_teams.exists():
            led_branch_ids = set(
                self.instance.led_teams.values_list("branch_id", flat=True)
            )
            if role != User.Role.TEAM_LEADER:
                raise serializers.ValidationError(
                    {"role": "A user leading a team must retain the Team Leader role."}
                )
            if branch.id not in led_branch_ids or len(led_branch_ids) != 1:
                raise serializers.ValidationError(
                    {
                        "branch": "Move or reassign this user's teams before changing branches."
                    }
                )
        password = attrs.get("password")
        if not self.instance and not password:
            raise serializers.ValidationError(
                {"password": "A temporary password is required."}
            )
        if password:
            candidate = self.instance or User(email=attrs.get("email", ""))
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(
                    {"password": list(exc.messages)}
                ) from exc
        return attrs

    def create(self, validated_data):
        assignments = validated_data.pop("project_assignment_ids", [])
        password = validated_data.pop("password")
        with transaction.atomic():
            user = User.objects.create_user(
                password=password, is_staff=False, **validated_data
            )
            QAProjectAssignment.objects.bulk_create(
                [
                    QAProjectAssignment(qa=user, dialer_campaign=assignment)
                    for assignment in assignments
                ]
            )
        return user

    def update(self, instance, validated_data):
        assignments_provided = "project_assignment_ids" in validated_data
        assignments = validated_data.pop("project_assignment_ids", [])
        password = validated_data.pop("password", "")
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            if password:
                instance.set_password(password)
                instance.must_change_password = True
            instance.full_clean()
            instance.save()
            if instance.role != User.Role.QA:
                instance.qa_project_assignments.all().delete()
            elif assignments_provided:
                instance.qa_project_assignments.all().delete()
                QAProjectAssignment.objects.bulk_create(
                    [
                        QAProjectAssignment(qa=instance, dialer_campaign=assignment)
                        for assignment in assignments
                    ]
                )
        return instance

    def get_assigned_projects(self, obj):
        return [
            {
                "id": str(assignment.dialer_campaign_id),
                "dialer_id": str(assignment.dialer_campaign.dialer_id),
                "dialer_name": assignment.dialer_campaign.dialer.name,
                "campaign": assignment.dialer_campaign.campaign,
                "project_name": assignment.dialer_campaign.project_name,
            }
            for assignment in obj.qa_project_assignments.all()
        ]


class AuthenticationEventAdminSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    event_label = serializers.CharField(source="get_event_display", read_only=True)

    class Meta:
        model = AuthenticationEvent
        fields = (
            "id",
            "user_name",
            "email",
            "event",
            "event_label",
            "ip_address",
            "user_agent",
            "created_at",
        )
