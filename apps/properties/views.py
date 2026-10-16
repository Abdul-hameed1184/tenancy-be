from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.cache import cached
from apps.common.permissions import HasRole, IsAgent, IsLandlord, IsOwner, ensure_self

from . import selectors, services
from .models import Property, PropertyTenantRequest
from .filters import PropertyFilter
from .serializers import (
    AgentAssignmentSerializer,
    AssignAgentSerializer,
    PropertyTenantRequestSerializer,
    PropertyCreateSerializer,
    PropertySerializer,
    PropertyUpdateSerializer,
    TenantCandidateSerializer,
    TenantRequestCreateSerializer,
    TenantRequestDecisionSerializer,
)

TAGS = ["properties"]


@extend_schema_view(
    list=extend_schema(tags=TAGS, summary="List properties (public)"),
    retrieve=extend_schema(tags=TAGS, summary="Get a property (public)"),
    create=extend_schema(
        tags=TAGS, request=PropertyCreateSerializer, responses={201: PropertySerializer}
    ),
    partial_update=extend_schema(
        tags=TAGS, request=PropertyUpdateSerializer, responses={200: PropertySerializer}
    ),
)
class PropertyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    # No DELETE and no full PUT: neither is in the contract.
    http_method_names = ["get", "post", "patch", "put", "delete", "head", "options"]
    filterset_class = PropertyFilter
    owner_field = "landlord"

    def get_queryset(self):
        return selectors.property_catalogue()

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsLandlord()]
        # partial_update, agent: only the owning landlord.
        return [IsLandlord(), IsOwner()]

    def get_serializer_class(self):
        return {
            "create": PropertyCreateSerializer,
            "partial_update": PropertyUpdateSerializer,
        }.get(self.action, PropertySerializer)

    # The catalogue is identical for every caller, so whole responses are cacheable.
    CACHE_TTL = 60

    def list(self, request, *args, **kwargs):
        data = cached(
            "properties",
            "list",
            request.query_params,
            self.CACHE_TTL,
            lambda: super(PropertyViewSet, self).list(request, *args, **kwargs).data,
        )
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        data = cached(
            "properties",
            "detail",
            {"pk": kwargs.get("pk")},
            self.CACHE_TTL,
            lambda: super(PropertyViewSet, self).retrieve(request, *args, **kwargs).data,
        )
        return Response(data)

    def update(self, request, *args, **kwargs):
        if not kwargs.get("partial"):
            return Response(
                {"message": "Use PATCH to update a property."},
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        prop = services.create_property(
            landlord=self.request.user, data=serializer.validated_data, request=self.request
        )
        serializer.instance = self._reload(prop.pk)

    def perform_update(self, serializer):
        prop = services.update_property(
            prop=serializer.instance,
            actor=self.request.user,
            data=serializer.validated_data,
            request=self.request,
        )
        serializer.instance = self._reload(prop.pk)

    @extend_schema(
        tags=TAGS,
        methods=["PUT"],
        request=AssignAgentSerializer,
        responses={200: AgentAssignmentSerializer},
        summary="Assign the managing agent (replaces any current one)",
    )
    @extend_schema(tags=TAGS, methods=["DELETE"], responses={204: None}, summary="Remove the agent")
    @action(detail=True, methods=["put", "delete"], url_path="agent")
    def agent(self, request, pk=None):
        prop = self.get_object()  # runs IsOwner against the property
        if request.method == "DELETE":
            services.unassign_agent(prop=prop, actor=request.user, request=request)
            return Response(status=status.HTTP_204_NO_CONTENT)

        body = AssignAgentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            assignment = services.assign_agent(
                prop=prop,
                agent_id=body.validated_data["agentId"],
                actor=request.user,
                request=request,
            )
        except services.InvalidAgent as exc:
            raise ValidationError({"agentId": ["No active agent with this id."]}) from exc
        return Response(AgentAssignmentSerializer(assignment).data)

    @staticmethod
    def _reload(pk):
        return selectors.property_catalogue().get(pk=pk)


class TopAgentPropertiesView(APIView):
    permission_classes = [IsAgent]

    @extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("limit", int, description="1-50, default 3")],
        responses={200: PropertySerializer(many=True)},
        summary="An agent's properties ranked by occupancyRate x priceAnnual",
    )
    def get(self, request, agent_id):
        ensure_self(request.user, agent_id, what="properties")
        try:
            limit = int(request.query_params.get("limit", 3))
        except ValueError as exc:
            raise ValidationError({"limit": ["Must be an integer."]}) from exc
        if not 1 <= limit <= 50:
            raise ValidationError({"limit": ["Must be between 1 and 50."]})
        properties = selectors.top_for_agent(agent_id, limit)
        return Response(PropertySerializer(properties, many=True).data)


class PropertyTenantCandidatesView(APIView):
    permission_classes = [IsAgent]

    @extend_schema(
        tags=TAGS,
        parameters=[OpenApiParameter("search", str, description="Tenant name, at least 2 chars")],
        responses={200: TenantCandidateSerializer(many=True)},
    )
    def get(self, request, property_id):
        prop = get_object_or_404(Property, pk=property_id)
        try:
            tenants = services.tenant_candidates(
                prop=prop, agent=request.user, search=request.query_params.get("search", "")
            )
        except PermissionDenied as exc:
            raise NotFound("Property not found.") from exc
        return Response(TenantCandidateSerializer(tenants, many=True).data)


class PropertyTenantRequestView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAgent()]
        return [HasRole("agent", "landlord")()]

    @extend_schema(tags=TAGS, responses={200: PropertyTenantRequestSerializer(many=True)})
    def get(self, request, property_id):
        prop = get_object_or_404(Property, pk=property_id)
        if request.user.is_landlord and prop.landlord_id != request.user.pk:
            raise NotFound("Property not found.")
        if request.user.is_agent:
            try:
                services.require_property_agent(prop=prop, agent=request.user)
            except PermissionDenied as exc:
                raise NotFound("Property not found.") from exc
        rows = PropertyTenantRequest.objects.filter(property=prop).select_related("tenant")
        return Response(PropertyTenantRequestSerializer(rows, many=True).data)

    @extend_schema(
        tags=TAGS,
        request=TenantRequestCreateSerializer,
        responses={201: PropertyTenantRequestSerializer},
    )
    def post(self, request, property_id):
        prop = get_object_or_404(Property, pk=property_id)
        body = TenantRequestCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            tenant_request = services.request_tenant_change(
                prop=prop, actor=request.user, data=body.validated_data, request=request
            )
        except services.InvalidTenant as exc:
            raise ValidationError({"tenantId": [str(exc)]}) from exc
        return Response(
            PropertyTenantRequestSerializer(tenant_request).data, status=status.HTTP_201_CREATED
        )


class TenantRequestDecisionView(APIView):
    permission_classes = [IsLandlord]

    @extend_schema(
        tags=TAGS,
        request=TenantRequestDecisionSerializer,
        responses={200: PropertyTenantRequestSerializer},
    )
    def post(self, request, request_id):
        body = TenantRequestDecisionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            tenant_request = services.decide_tenant_change(
                request_id=request_id,
                landlord=request.user,
                decision=body.validated_data["decision"],
                request=request,
            )
        except services.InvalidTenantRequest as exc:
            raise NotFound(str(exc)) from exc
        return Response(PropertyTenantRequestSerializer(tenant_request).data)
