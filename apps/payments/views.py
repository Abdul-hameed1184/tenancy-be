from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import HasRole
from apps.tenancies.selectors import visible_to as tenancies_visible_to

from . import services
from .serializers import LogPaymentSerializer, PaymentEntrySerializer

TAGS = ["payments"]


class TenancyPaymentsView(APIView):
    """
    The ledger of one tenancy. Reading follows tenancy scope (owner landlord, managing
    agent, the tenant themself); logging is for the property's active agent only.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [HasRole("agent")()]
        return [HasRole("admin", "landlord", "agent", "tenant")()]

    def _tenancy(self, request, pk):
        return get_object_or_404(tenancies_visible_to(request.user), pk=pk)

    @extend_schema(tags=TAGS, responses={200: PaymentEntrySerializer(many=True)})
    def get(self, request, pk):
        tenancy = self._tenancy(request, pk)
        entries = tenancy.payments.order_by("due_date", "logged_at")
        return Response(PaymentEntrySerializer(entries, many=True).data)

    @extend_schema(tags=TAGS, request=LogPaymentSerializer, responses={201: PaymentEntrySerializer})
    def post(self, request, pk):
        tenancy = self._tenancy(request, pk)  # agents only see managed tenancies -> 404
        body = LogPaymentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            entry = services.log_payment(
                tenancy=tenancy, agent=request.user, data=body.validated_data, request=request
            )
        except services.NotManagingAgent as exc:
            raise PermissionDenied("You no longer manage this property.") from exc
        return Response(PaymentEntrySerializer(entry).data, status=status.HTTP_201_CREATED)
