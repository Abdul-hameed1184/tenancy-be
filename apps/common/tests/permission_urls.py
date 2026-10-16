"""Throwaway endpoints that exercise each permission building block in isolation."""

from django_filters import rest_framework as filters
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AuthSession, User
from apps.common.permissions import (
    HasRole,
    IsAdmin,
    IsAgent,
    IsLandlord,
    IsOwner,
    IsTenant,
    ScopedQuerysetMixin,
    ensure_self,
)
from apps.common.routers import OptionalSlashRouter, optional_slash


def ok_view(*permissions):
    class View(APIView):
        permission_classes = list(permissions)

        def get(self, request):
            return Response({"ok": True})

    return View.as_view()


def users_visible_to(user):
    """Admins see everyone; everybody else sees only themselves."""
    qs = User.objects.order_by("email")
    return qs if user.is_admin else qs.filter(pk=user.pk)


class UserFilter(filters.FilterSet):
    # Mirrors contract-style id filters (?landlordId=...): applied inside the scope.
    userId = filters.UUIDFilter(field_name="id")

    class Meta:
        model = User
        fields = ["userId"]


class UserOut(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email"]


class ScopedUserViewSet(ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    visible_to = staticmethod(users_visible_to)
    serializer_class = UserOut
    filterset_class = UserFilter
    permission_classes = [HasRole(*User.Role.values)]


class SessionOut(serializers.ModelSerializer):
    class Meta:
        model = AuthSession
        fields = ["id", "user_agent"]


class OwnedSessionViewSet(mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Unscoped on purpose, so IsOwner alone is what blocks a non-owner."""

    queryset = AuthSession.objects.all()
    serializer_class = SessionOut
    permission_classes = [HasRole(*User.Role.values), IsOwner]
    owner_field = "user"


class SelfOnlyView(APIView):
    permission_classes = [HasRole(*User.Role.values)]

    def get(self, request):
        ensure_self(request.user, request.query_params.get("userId"), allow_admin=True)
        return Response({"ok": True})


router = OptionalSlashRouter()
router.register("users", ScopedUserViewSet, basename="scoped-user")
router.register("sessions", OwnedSessionViewSet, basename="owned-session")

urlpatterns = [
    *optional_slash("admin-only", ok_view(IsAdmin)),
    *optional_slash("landlord-only", ok_view(IsLandlord)),
    *optional_slash("agent-only", ok_view(IsAgent)),
    *optional_slash("tenant-only", ok_view(IsTenant)),
    *optional_slash("agent-or-tenant", ok_view(HasRole("agent", "tenant"))),
    *optional_slash("self-only", SelfOnlyView.as_view()),
    *router.urls,
]
