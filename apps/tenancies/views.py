from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasRole, IsTenant, ScopedQuerysetMixin, ensure_self

from . import selectors
from .filters import TenancyFilter
from .serializers import TenancyDetailSerializer

TAGS = ["tenancies"]


@extend_schema_view(
    list=extend_schema(tags=TAGS, summary="Tenancies on properties you own or manage"),
    retrieve=extend_schema(tags=TAGS),
)
class TenancyViewSet(ScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    visible_to = staticmethod(selectors.visible_to)
    serializer_class = TenancyDetailSerializer
    filterset_class = TenancyFilter
    # Tenants read their own tenancy via /tenants/:id/tenancy, as the contract specifies.
    permission_classes = [HasRole("admin", "landlord", "agent")]


class TenantTenancyView(APIView):
    permission_classes = [IsTenant]

    @extend_schema(tags=TAGS, responses={200: TenancyDetailSerializer})
    def get(self, request, tenant_id):
        ensure_self(request.user, tenant_id, what="tenancy")
        tenancy = selectors.visible_to(request.user).first()
        if tenancy is None:
            raise NotFound("You don't have a current tenancy.")
        return Response(TenancyDetailSerializer(tenancy).data)
