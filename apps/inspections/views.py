from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.permissions import HasRole, ScopedQuerysetMixin

from . import selectors, services
from .filters import InspectionFilter
from .serializers import InspectionSerializer, RequestInspectionSerializer

TAGS = ["inspections"]


@extend_schema_view(
    list=extend_schema(tags=TAGS, summary="Inspections in your scope, soonest first"),
    retrieve=extend_schema(tags=TAGS),
    create=extend_schema(
        tags=TAGS, request=RequestInspectionSerializer, responses={201: InspectionSerializer}
    ),
)
class InspectionViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Status changes are explicit commands (confirm/complete/cancel), not a free PATCH: each
    endpoint names one legal transition, which the service applies atomically.
    """

    visible_to = staticmethod(selectors.visible_to)
    serializer_class = InspectionSerializer
    filterset_class = InspectionFilter

    def get_permissions(self):
        roles = {
            "create": ("tenant",),
            "confirm": ("agent",),
            "complete": ("agent",),
            "cancel": ("agent", "tenant"),
        }.get(self.action, ("admin", "landlord", "agent", "tenant"))
        return [HasRole(*roles)()]

    def create(self, request):
        body = RequestInspectionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            insp = services.request_inspection(
                tenant=request.user, data=body.validated_data, request=request
            )
        except services.BookingError as exc:
            raise ValidationError({"propertyId": [str(exc)]}) from exc
        return Response(InspectionSerializer(insp).data, status=status.HTTP_201_CREATED)

    def _transition(self, request, name):
        # Scoped lookup: an agent only reaches their own inspections, a tenant their own
        # bookings; anything else is a 404.
        insp = self.get_object()
        updated = services.apply_transition(
            insp=insp, action=name, actor=request.user, request=request
        )
        return Response(InspectionSerializer(updated).data)

    @extend_schema(tags=TAGS, request=None, responses={200: InspectionSerializer})
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._transition(request, "confirm")

    @extend_schema(tags=TAGS, request=None, responses={200: InspectionSerializer})
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._transition(request, "complete")

    @extend_schema(tags=TAGS, request=None, responses={200: InspectionSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition(request, "cancel")
