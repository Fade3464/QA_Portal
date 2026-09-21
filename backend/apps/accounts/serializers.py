from rest_framework import serializers

from .models import User


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        trim_whitespace=False, write_only=True, max_length=128
    )
    remember = serializers.BooleanField(default=False)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=128)
    token = serializers.CharField(max_length=256)
    password = serializers.CharField(write_only=True, max_length=128)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, max_length=128)
    password = serializers.CharField(write_only=True, max_length=128)


class CurrentUserSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="full_name", read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    company = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    profile_picture_url = serializers.SerializerMethodField()
    appearance = serializers.SerializerMethodField()
    assigned_projects = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "name",
            "first_name",
            "last_name",
            "role",
            "role_label",
            "company",
            "branch",
            "must_change_password",
            "is_superuser",
            "profile_picture_url",
            "appearance",
            "assigned_projects",
        )

    def get_company(self, obj):
        return (
            {"id": str(obj.company_id), "name": obj.company.name}
            if obj.company_id
            else None
        )

    def get_branch(self, obj):
        return (
            {"id": str(obj.branch_id), "name": obj.branch.name, "code": obj.branch.code}
            if obj.branch_id
            else None
        )

    def get_profile_picture_url(self, obj):
        if not obj.profile_picture:
            return None
        version = int(obj.updated_at.timestamp() * 1_000_000)
        return f"/api/v1/auth/account/avatar/?v={version}"

    def get_appearance(self, obj):
        return {
            "mode": obj.appearance_mode,
            "preset": obj.appearance_preset,
            "compact": obj.appearance_compact,
        }

    def get_assigned_projects(self, obj):
        assignments = obj.qa_project_assignments.select_related(
            "dialer_campaign__dialer"
        ).all()
        return [
            {
                "id": str(item.dialer_campaign_id),
                "name": item.dialer_campaign.project_name,
                "campaign": item.dialer_campaign.campaign,
                "dialer": item.dialer_campaign.dialer.name,
            }
            for item in assignments
        ]


class AppearanceSerializer(serializers.ModelSerializer):
    mode = serializers.ChoiceField(
        source="appearance_mode", choices=User.AppearanceMode.choices
    )
    preset = serializers.ChoiceField(
        source="appearance_preset", choices=User.AppearancePreset.choices
    )
    compact = serializers.BooleanField(source="appearance_compact")

    class Meta:
        model = User
        fields = ("mode", "preset", "compact")
