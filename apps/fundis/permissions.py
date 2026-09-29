from rest_framework.permissions import BasePermission


class HasFundiProfile(BasePermission):
    message = "Create a fundi profile first."

    def has_permission(self, request, view):
        return request.user.is_authenticated and hasattr(request.user, "fundi_profile")
