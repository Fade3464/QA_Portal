from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import AuthenticationEvent, User

from .models import Branch, Company, Dialer


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


class DialerAdminSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    company_name = serializers.CharField(source="branch.company.name", read_only=True)
    api_password = serializers.CharField(write_only=True, required=False, allow_blank=False)
    webhook_secret = serializers.CharField(write_only=True, required=False, allow_blank=False)
    webhook_path = serializers.SerializerMethodField()

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
            "allowed_recording_hosts",
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
                raise serializers.ValidationError({"api_password": "An API password is required."})
            if not attrs.get("webhook_secret"):
                raise serializers.ValidationError({"webhook_secret": "A webhook secret is required."})
        return attrs

    def create(self, validated_data):
        api_password = validated_data.pop("api_password")
        webhook_secret = validated_data.pop("webhook_secret")
        dialer = Dialer(**validated_data)
        dialer.set_api_password(api_password)
        dialer.set_webhook_secret(webhook_secret)
        dialer.full_clean()
        dialer.save()
        return dialer

    def update(self, instance, validated_data):
        api_password = validated_data.pop("api_password", "")
        webhook_secret = validated_data.pop("webhook_secret", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if api_password:
            instance.set_api_password(api_password)
        if webhook_secret:
            instance.set_webhook_secret(webhook_secret)
        instance.full_clean()
        instance.save()
        return instance


class UserAdminSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="full_name", read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False)

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
            "is_active",
            "must_change_password",
            "last_login",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "last_login", "created_at", "updated_at")

    def validate_role(self, value):
        if value == User.Role.ADMINISTRATOR:
            raise serializers.ValidationError("System administrators are created through the server console.")
        return value

    def validate(self, attrs):
        company = attrs.get("company", getattr(self.instance, "company", None))
        branch = attrs.get("branch", getattr(self.instance, "branch", None))
        if not company or not branch:
            raise serializers.ValidationError("A company and branch are required.")
        if branch.company_id != company.id:
            raise serializers.ValidationError({"branch": "The branch must belong to the selected company."})
        password = attrs.get("password")
        if not self.instance and not password:
            raise serializers.ValidationError({"password": "A temporary password is required."})
        if password:
            candidate = self.instance or User(email=attrs.get("email", ""))
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, is_staff=False, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
            instance.must_change_password = True
        instance.full_clean()
        instance.save()
        return instance


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
