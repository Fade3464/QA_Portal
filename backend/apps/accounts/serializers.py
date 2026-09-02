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
