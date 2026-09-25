from rest_framework.permissions import BasePermission


class IsSystemAdministrator(BasePermission):
    message = "System administrator access is required."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.is_active
            and request.user.is_superuser
        )
