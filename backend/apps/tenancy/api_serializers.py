import re
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import AuthenticationEvent, User
from .access import branch_projects
from .services import company_projects, sync_dialer_manager_project_access

from .models import (
    Branch,
    Company,
    Dialer,
    DialerCampaign,
    DialerFronterMapping,
    QAProjectAssignment,
    Team,
)


class CompanyAdminSerializer(serializers.ModelSerializer):
    branches_count = serializers.IntegerField(read_only=True)
    users_count = serializers.IntegerField(read_only=True)
    grafana_viewer_password = serializers.CharField(
        write_only=True, required=False, allow_blank=False, min_length=12
    )
    grafana_credentials_configured = serializers.SerializerMethodField()
    analytics_url = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = (
            "id",
            "name",
            "slug",
            "is_active",
            "analytics_enabled",
            "grafana_viewer_username",
            "grafana_viewer_password",
            "grafana_credentials_configured",
            "analytics_url",
            "branches_count",
            "users_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id", "grafana_credentials_configured", "analytics_url",
            "created_at", "updated_at"
        )

    def get_grafana_credentials_configured(self, obj):
        return bool(obj.grafana_viewer_password_ciphertext)

    def get_analytics_url(self, obj):
        return "/analytics/" if obj.analytics_enabled else ""

    def validate(self, attrs):
        enabled = attrs.get(
            "analytics_enabled",
            getattr(self.instance, "analytics_enabled", False),
        )
        username = attrs.get(
            "grafana_viewer_username",
            getattr(self.instance, "grafana_viewer_username", ""),
        ).strip()
        password = attrs.get("grafana_viewer_password", "")
        existing_password = bool(
            self.instance and self.instance.grafana_viewer_password_ciphertext
        )
        if enabled:
            errors = {}
            if not username:
                errors["grafana_viewer_username"] = "A shared Grafana viewer username is required."
            elif not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", username):
                errors["grafana_viewer_username"] = (
                    "Use 3-64 letters, numbers, dots, underscores, or hyphens."
                )
            elif username.casefold() == settings.GRAFANA_SERVICE_ADMIN_USER.casefold():
                errors["grafana_viewer_username"] = (
                    "The shared viewer username must differ from the internal Grafana administrator."
                )
            if not password and not existing_password:
                errors["grafana_viewer_password"] = "A shared Grafana viewer password is required."
            if password and not (
                re.search(r"[a-z]", password)
                and re.search(r"[A-Z]", password)
                and re.search(r"[0-9]", password)
                and re.search(r"[^A-Za-z0-9]", password)
            ):
                errors["grafana_viewer_password"] = (
                    "Use at least 12 characters with upper/lowercase, a number, and a symbol."
                )
            conflict = Company.objects.filter(analytics_enabled=True)
            if self.instance:
                conflict = conflict.exclude(pk=self.instance.pk)
            if conflict.exists():
                errors["analytics_enabled"] = (
                    "Sales analytics is already enabled for another company in this portal deployment."
                )
            if errors:
                raise serializers.ValidationError(errors)
        attrs["grafana_viewer_username"] = username
        return attrs

    @staticmethod
    def _queue_grafana_sync(company):
        from apps.analytics.tasks import sync_grafana_viewer
        transaction.on_commit(lambda: sync_grafana_viewer.delay(str(company.pk)))

    def create(self, validated_data):
        password = validated_data.pop("grafana_viewer_password", "")
        with transaction.atomic():
            company = Company(**validated_data)
            if password:
                company.set_grafana_viewer_password(password)
            company.full_clean()
            company.save()
            if company.analytics_enabled:
                self._queue_grafana_sync(company)
        return company

    def update(self, instance, validated_data):
        password = validated_data.pop("grafana_viewer_password", "")
        with transaction.atomic():
            for field, value in validated_data.items():
                setattr(instance, field, value)
            if password:
                instance.set_grafana_viewer_password(password)
            instance.full_clean()
            instance.save()
            # Queue on both enable and disable so a previously-created viewer
            # account is removed when analytics is turned off.
            if instance.analytics_enabled or instance.grafana_user_id:
                self._queue_grafana_sync(instance)
        return instance


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


class DialerFronterMappingAdminSerializer(serializers.ModelSerializer):
    # fronter_dialer is a OneToOneField, so DRF would normally attach an
    # automatic UniqueValidator. In this nested serializer DRF has no child
    # instance during a parent update, making unchanged mappings look like
    # duplicates. Ownership is validated in DialerAdminSerializer.validate(),
    # while the database OneToOne constraint remains the concurrency-safe guard.
    fronter_dialer = serializers.PrimaryKeyRelatedField(
        queryset=Dialer.objects.all(),
        validators=[],
    )
    fronter_dialer_name = serializers.CharField(source="fronter_dialer.name", read_only=True)

    class Meta:
        model = DialerFronterMapping
        fields = ("id", "fronter_dialer", "fronter_dialer_name", "ingroup_name")
        read_only_fields = ("id", "fronter_dialer_name")


class DialerAdminSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    company_name = serializers.CharField(source="branch.company.name", read_only=True)
    fronter_mappings = DialerFronterMappingAdminSerializer(many=True, required=False)
    mapped_closer_dialer = serializers.SerializerMethodField()
    mapped_closer_dialer_name = serializers.SerializerMethodField()
    api_password = serializers.CharField(
        write_only=True, required=False, allow_blank=False
    )
    webhook_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=False
    )
    preset_lookup_password = serializers.CharField(
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
            "is_closer",
            "fronter_mappings",
            "mapped_closer_dialer",
            "mapped_closer_dialer_name",
            "api_url",
            "api_username",
            "api_password",
            "api_source",
            "preset_lookup_url",
            "preset_lookup_username",
            "preset_lookup_password",
            "preset_lookup_verify_tls",
            "webhook_secret",
            "webhook_path",
            "campaigns",
            "request_timeout_seconds",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "mapped_closer_dialer",
            "mapped_closer_dialer_name",
            "webhook_path",
            "created_at",
            "updated_at",
        )

    def get_webhook_path(self, obj):
        return f"/api/v1/webhooks/vicidial/{obj.id}/dispo/"

    def _incoming_closer_mapping(self, obj):
        try:
            return obj.closer_mapping
        except DialerFronterMapping.DoesNotExist:
            return None

    def get_mapped_closer_dialer(self, obj):
        mapping = self._incoming_closer_mapping(obj)
        return str(mapping.closer_dialer_id) if mapping else None

    def get_mapped_closer_dialer_name(self, obj):
        mapping = self._incoming_closer_mapping(obj)
        return mapping.closer_dialer.name if mapping else None

    def validate(self, attrs):
        is_closer = attrs.get(
            "is_closer",
            getattr(self.instance, "is_closer", False),
        )
        if not self.instance:
            if not attrs.get("api_password"):
                raise serializers.ValidationError(
                    {"api_password": "An API password is required."}
                )
            if is_closer and not attrs.get("webhook_secret"):
                raise serializers.ValidationError(
                    {"webhook_secret": "A webhook secret is required for a closer dialer."}
                )

        lookup_url = attrs.get(
            "preset_lookup_url",
            getattr(self.instance, "preset_lookup_url", ""),
        )
        lookup_username = attrs.get(
            "preset_lookup_username",
            getattr(self.instance, "preset_lookup_username", ""),
        )
        lookup_password = attrs.get("preset_lookup_password", "")
        existing_lookup_password = bool(
            self.instance and self.instance.preset_lookup_password_ciphertext
        )
        configured_parts = bool(
            lookup_url or lookup_username or lookup_password or existing_lookup_password
        )
        if configured_parts:
            errors = {}
            if not lookup_url:
                errors["preset_lookup_url"] = (
                    "User Stats URL is required when preset lookup is configured."
                )
            if not lookup_username:
                errors["preset_lookup_username"] = (
                    "User Stats username is required when preset lookup is configured."
                )
            if not lookup_password and not existing_lookup_password:
                errors["preset_lookup_password"] = (
                    "User Stats password is required when preset lookup is configured."
                )
            if errors:
                raise serializers.ValidationError(errors)

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

        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        fronter_mappings = attrs.get("fronter_mappings")

        # A fronter already owned by a closer cannot silently become a closer or
        # move to another company while that ownership exists.
        incoming_mapping = None
        if self.instance:
            incoming_mapping = DialerFronterMapping.objects.filter(
                fronter_dialer=self.instance
            ).select_related("closer_dialer__branch__company").first()
        if incoming_mapping:
            if is_closer:
                raise serializers.ValidationError(
                    {
                        "is_closer": (
                            f"This fronter is already mapped to closer "
                            f"{incoming_mapping.closer_dialer.name}. Remove that mapping first."
                        )
                    }
                )
            if branch and branch.company_id != incoming_mapping.closer_dialer.branch.company_id:
                raise serializers.ValidationError(
                    {
                        "branch": (
                            "A mapped fronter cannot be moved to another company. "
                            "Remove its closer mapping first."
                        )
                    }
                )

        if is_closer:
            effective_mappings = fronter_mappings
            if effective_mappings is None:
                if self.instance and self.instance.is_closer:
                    effective_mappings = list(
                        self.instance.fronter_mappings.select_related(
                            "fronter_dialer__branch__company"
                        ).values(
                            "fronter_dialer",
                            "ingroup_name",
                        )
                    )
                else:
                    effective_mappings = []

            if not effective_mappings:
                raise serializers.ValidationError(
                    {"fronter_mappings": "Map at least one fronter dialer to this closer."}
                )

            errors = []
            seen_fronters = set()
            normalized = []
            for index, mapping in enumerate(effective_mappings):
                fronter = mapping.get("fronter_dialer")
                if fronter and not isinstance(fronter, Dialer):
                    fronter = Dialer.objects.select_related("branch__company").filter(
                        pk=fronter
                    ).first()
                raw_ingroup_name = mapping.get("ingroup_name") or ""
                try:
                    ingroup_name, _ = DialerFronterMapping.normalize_ingroup_names(
                        raw_ingroup_name
                    )
                    ingroup_error = None
                except DjangoValidationError as exc:
                    ingroup_name = raw_ingroup_name
                    ingroup_error = " ".join(exc.messages)
                item_errors = {}
                if not fronter:
                    item_errors["fronter_dialer"] = "Choose a fronter dialer."
                else:
                    if self.instance and fronter.pk == self.instance.pk:
                        item_errors["fronter_dialer"] = (
                            "A closer dialer cannot map to itself."
                        )
                    elif fronter.is_closer:
                        item_errors["fronter_dialer"] = (
                            "A closer dialer can only map fronter dialers."
                        )
                    elif branch and fronter.branch.company_id != branch.company_id:
                        item_errors["fronter_dialer"] = (
                            "The fronter and closer dialers must belong to the same company."
                        )
                    elif fronter.pk in seen_fronters:
                        item_errors["fronter_dialer"] = (
                            "This fronter is listed more than once."
                        )
                    else:
                        owner_qs = DialerFronterMapping.objects.filter(
                            fronter_dialer=fronter
                        )
                        if self.instance:
                            owner_qs = owner_qs.exclude(closer_dialer=self.instance)
                        owner = owner_qs.select_related("closer_dialer").first()
                        if owner:
                            item_errors["fronter_dialer"] = (
                                f"This fronter is already mapped to closer "
                                f"{owner.closer_dialer.name}."
                            )
                    seen_fronters.add(fronter.pk)
                if ingroup_error:
                    item_errors["ingroup_name"] = ingroup_error
                if item_errors:
                    errors.append({"index": index, **item_errors})
                elif fronter_mappings is not None:
                    normalized.append(
                        {"fronter_dialer": fronter, "ingroup_name": ingroup_name}
                    )
            if errors:
                raise serializers.ValidationError({"fronter_mappings": errors})
            if fronter_mappings is not None:
                attrs["fronter_mappings"] = normalized
        else:
            if fronter_mappings:
                raise serializers.ValidationError(
                    {"fronter_mappings": "Fronter mappings are only available for closer dialers."}
                )
            # When a closer is converted back to a fronter its owned mappings
            # are removed during update().
            if fronter_mappings is not None:
                attrs["fronter_mappings"] = []
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

    @staticmethod
    def _replace_fronter_mappings(dialer, mappings):
        existing = {
            item.fronter_dialer_id: item
            for item in dialer.fronter_mappings.select_related("fronter_dialer")
        }
        retained_ids = []
        for mapping in mappings:
            fronter = mapping["fronter_dialer"]
            current = existing.get(fronter.pk)
            if current:
                current.ingroup_name = mapping["ingroup_name"]
                current.full_clean()
                current.save(update_fields=["ingroup_name", "updated_at"])
            else:
                current = DialerFronterMapping(
                    closer_dialer=dialer,
                    fronter_dialer=fronter,
                    ingroup_name=mapping["ingroup_name"],
                )
                current.full_clean()
                current.save()
            retained_ids.append(current.pk)
        dialer.fronter_mappings.exclude(pk__in=retained_ids).delete()

    def create(self, validated_data):
        campaigns = validated_data.pop("campaigns", [])
        fronter_mappings = validated_data.pop("fronter_mappings", [])
        api_password = validated_data.pop("api_password")
        webhook_secret = validated_data.pop("webhook_secret", "")
        preset_lookup_password = validated_data.pop("preset_lookup_password", "")
        with transaction.atomic():
            dialer = Dialer(**validated_data)
            dialer.set_api_password(api_password)
            if preset_lookup_password:
                dialer.set_preset_lookup_password(preset_lookup_password)
            if webhook_secret:
                dialer.set_webhook_secret(webhook_secret)
            dialer.full_clean()
            dialer.save()
            if dialer.is_closer:
                self._replace_fronter_mappings(dialer, fronter_mappings)
            self._replace_campaigns(dialer, campaigns)
        return dialer

    def update(self, instance, validated_data):
        campaigns = validated_data.pop("campaigns", None)
        fronter_mappings = validated_data.pop("fronter_mappings", None)
        api_password = validated_data.pop("api_password", "")
        webhook_secret = validated_data.pop("webhook_secret", "")
        preset_lookup_password = validated_data.pop("preset_lookup_password", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if api_password:
            instance.set_api_password(api_password)
        if preset_lookup_password:
            instance.set_preset_lookup_password(preset_lookup_password)
        if webhook_secret:
            instance.set_webhook_secret(webhook_secret)
        with transaction.atomic():
            instance.full_clean()
            instance.save()
            if not instance.is_closer:
                instance.fronter_mappings.all().delete()
            elif fronter_mappings is not None:
                self._replace_fronter_mappings(instance, fronter_mappings)
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
            "call_editor_access",
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
        project_scoped_roles = {
            User.Role.QA,
            User.Role.TEAM_LEADER,
            User.Role.PROJECT_MANAGER,
        }
        editor_access = attrs.get(
            "call_editor_access",
            getattr(self.instance, "call_editor_access", False),
        )
        if editor_access and role != User.Role.PROJECT_MANAGER:
            raise serializers.ValidationError(
                {"call_editor_access": "Call editor access is only available to Project Managers."}
            )
        if role != User.Role.PROJECT_MANAGER:
            attrs["call_editor_access"] = False

        if role in project_scoped_roles:
            if role in {User.Role.QA, User.Role.PROJECT_MANAGER} and not assignments:
                raise serializers.ValidationError(
                    {
                        "project_assignment_ids": (
                            "Assign at least one dialer project to every QA or "
                            "Project Manager user."
                        )
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
                    "project_assignment_ids": (
                        "Project access can only be assigned to QA, Team Leader, "
                        "or Project Manager users."
                    )
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
            if user.role == User.Role.DIALER_MANAGER:
                sync_dialer_manager_project_access(user)
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
            if instance.role not in {
                User.Role.QA,
                User.Role.TEAM_LEADER,
                User.Role.PROJECT_MANAGER,
                User.Role.DIALER_MANAGER,
            }:
                instance.qa_project_assignments.all().delete()
            elif instance.role == User.Role.DIALER_MANAGER:
                sync_dialer_manager_project_access(instance)
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
        if obj.role == User.Role.DIALER_MANAGER and not obj.is_superuser:
            projects = company_projects(obj)
            return [
                {
                    "id": str(project.pk),
                    "dialer_id": str(project.dialer_id),
                    "dialer_name": project.dialer.name,
                    "campaign": project.campaign,
                    "project_name": project.project_name,
                }
                for project in projects
            ]
        if obj.role == User.Role.SUPERVISOR and not obj.is_superuser:
            return [
                {
                    "id": str(project.pk),
                    "dialer_id": str(project.dialer_id),
                    "dialer_name": project.dialer.name,
                    "campaign": project.campaign,
                    "project_name": project.project_name,
                }
                for project in branch_projects(obj)
            ]
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
