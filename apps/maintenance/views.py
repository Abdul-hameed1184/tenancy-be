from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.permissions import HasRole, ScopedQuerysetMixin

from . import selectors, services
from .filters import MaintenanceFilter
from .serializers import (
    CreateMaintenanceSerializer,
    MaintenanceRequestSerializer,
    UpdateMaintenanceStatusSerializer,
)

TAGS = ["maintenance"]
ANY_ROLE = HasRole("admin", "landlord", "agent", "tenant")


@extend_schema_view(
    list=extend_schema(tags=TAGS, summary="Maintenance requests in your scope, newest first"),
    retrieve=extend_schema(tags=TAGS),
    create=extend_schema(
        tags=TAGS,
        request=CreateMaintenanceSerializer,
        responses={201: MaintenanceRequestSerializer},
    ),
    partial_update=extend_schema(
        tags=TAGS,
        request=UpdateMaintenanceStatusSerializer,
        responses={200: MaintenanceRequestSerializer},
        summary="Advance status: reported -> in_progress -> completed",
    ),
)
class MaintenanceViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    visible_to = staticmethod(selectors.visible_to)
    serializer_class = MaintenanceRequestSerializer
    filterset_class = MaintenanceFilter
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.action == "create":
            return [HasRole("tenant")()]
        if self.action == "partial_update":
            # Agents only see requests on properties they actively manage, so the scoped
            # lookup in get_object() doubles as the "is this my property?" check.
            return [HasRole("agent")()]
        return [ANY_ROLE()]

    def create(self, request):
        body = CreateMaintenanceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            req = services.create_request(
                tenant=request.user, data=body.validated_data, request=request
            )
        except services.NotYourProperty as exc:
            raise ValidationError(
                {"propertyId": ["You can only report issues for the property you rent."]}
            ) from exc
        return Response(MaintenanceRequestSerializer(req).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        req = self.get_object()
        body = UpdateMaintenanceStatusSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        updated = services.change_status(
            req=req, to=body.validated_data["status"], actor=request.user, request=request
        )
        return Response(MaintenanceRequestSerializer(updated).data)
