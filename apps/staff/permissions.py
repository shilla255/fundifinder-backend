from rest_framework.permissions import BasePermission


class IsStaff(BasePermission):
    """Active staff accounts only (Django `is_staff`)."""

    message = "Staff only."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_staff)
