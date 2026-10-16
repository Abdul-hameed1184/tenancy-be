"""
Authorization building blocks.

Layer 1 - role (RBAC):     IsAdmin / IsLandlord / IsAgent / IsTenant / HasRole(...)
Layer 2 - scope:           ScopedQuerysetMixin: rows outside visible_to(user) are 404s
Layer 3 - object:          ObjectPermission subclasses (IsOwner here; IsPropertyManager and
                           IsThreadParticipant live with their models)

Identity always comes from request.user. Ids in URLs, bodies or query strings are inputs to
validate against it, never a source of authority (see ensure_self).
"""

from collections.abc import Callable
from typing import ClassVar

from django.db.models import QuerySet
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.accounts.models import User

# --- Layer 0: verified email ----------------------------------------------------------------

EMAIL_NOT_VERIFIED = "email_not_verified"


class EmailNotVerified(PermissionDenied):
    """403 with a machine-readable code, so the frontend can route to "check your inbox"."""

    default_detail = "Please verify your email address to continue."
    default_code = EMAIL_NOT_VERIFIED


def require_verified_email(user) -> None:
    if not user.is_email_verified:
        raise EmailNotVerified


class IsVerified(IsAuthenticated):
    """Authenticated *and* email verified. Use instead of IsAuthenticated on app features."""

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False  # anonymous: DRF answers 401, which makes the frontend log in
        require_verified_email(request.user)
        return True


# --- Layer 1: roles -------------------------------------------------------------------------


class RolePermission(BasePermission):
    """
    Grants access to authenticated users whose role is in `roles`.

    An anonymous request fails here too, and DRF turns that into 401 (not 403) because an
    authenticator is configured, which is what makes the frontend redirect to login.
    """

    roles: ClassVar[frozenset[str]] = frozenset()

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.role in self.roles):
            return False
        # Every role-gated endpoint is a dashboard feature: an unverified account may sign
        # in (to see "check your inbox") but can't use any of them.
        require_verified_email(user)
        return True

    @property
    def message(self) -> str:
        names = " or ".join(sorted(f"{r}s" for r in self.roles))
        return f"This action is only available to {names}."


def HasRole(*roles: str) -> type[RolePermission]:
    """`permission_classes = [HasRole("agent", "tenant")]`"""
    unknown = set(roles) - set(User.Role.values)
    if unknown:
        raise ValueError(f"Unknown roles: {sorted(unknown)}")
    return type(
        f"HasRole_{'_'.join(sorted(roles))}", (RolePermission,), {"roles": frozenset(roles)}
    )


IsAdmin = HasRole(User.Role.ADMIN)
IsLandlord = HasRole(User.Role.LANDLORD)
IsAgent = HasRole(User.Role.AGENT)
IsTenant = HasRole(User.Role.TENANT)


# --- Layer 2: scope -------------------------------------------------------------------------


class ScopedQuerysetMixin:
    """
    Every list and detail lookup starts from `visible_to(user)`.

    DRF's get_object() fetches through get_queryset(), so an object outside the user's scope
    is a 404, not a 403: we don't confirm that someone else's resource exists. Filters from
    the query string are applied after scoping (by DRF's filter backends), so they can only
    narrow what the user may already see.

    Views set `visible_to = staticmethod(some_selector)`; selectors live in each app.
    """

    visible_to: Callable[[User], QuerySet]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Schema generation introspects views with an anonymous request.
            return self.get_serializer_class().Meta.model.objects.none()
        return self.visible_to(self.request.user)


# --- Layer 3: objects -----------------------------------------------------------------------


class ObjectPermission(BasePermission):
    """Base for object rules. View-level access is left to the role permissions."""

    def has_permission(self, request, view) -> bool:
        return True

    def has_object_permission(self, request, view, obj) -> bool:
        return request.user.is_authenticated and self.allows(request.user, obj)

    def allows(self, user: User, obj) -> bool:
        raise NotImplementedError


class IsOwner(ObjectPermission):
    """
    The object's `owner_field` (default "user") is the requester. For example, a landlord's
    property sets `owner_field = "landlord"` on the view.
    """

    message = "You can only modify your own resources."

    def has_object_permission(self, request, view, obj) -> bool:
        field = getattr(view, "owner_field", "user")
        return request.user.is_authenticated and getattr(obj, f"{field}_id") == request.user.pk


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view) -> bool:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return bool(request.user.is_authenticated and request.user.is_admin)


# --- Identity checks for ids supplied by the client -----------------------------------------


def ensure_self(user: User, claimed_id, *, allow_admin: bool = False, what: str = "data") -> None:
    """
    Reject a request whose user id (URL segment, `?userId=`, `senderId` in a body...) is not
    the authenticated user. `None`/empty means "not supplied" and defaults to self.
    """
    if claimed_id in (None, ""):
        return
    if allow_admin and user.is_admin:
        return
    if str(claimed_id) != str(user.pk):
        raise PermissionDenied(f"You can only access your own {what}.")
