from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.common.fields import ContractDateField
from apps.payments.serializers import PaymentEntrySerializer
from apps.properties.serializers import PropertySerializer

from .models import Tenancy


class TenancyDetailSerializer(serializers.ModelSerializer):
    """
    The contract's TenancyDetail. Expects querysets from selectors.tenancy_details(), which
    joins tenant and property and annotates the property's active agent.
    """

    tenantId = serializers.UUIDField(source="tenant_id", read_only=True)
    propertyId = serializers.UUIDField(source="property_id", read_only=True)
    leaseStart = ContractDateField(source="lease_start", read_only=True)
    nextDueDate = ContractDateField(source="next_due_date", read_only=True)
    paymentHistory = serializers.SerializerMethodField()
    tenant = UserSerializer(read_only=True)
    property = serializers.SerializerMethodField()

    class Meta:
        model = Tenancy
        fields = [
            "id",
            "tenantId",
            "propertyId",
            "unit",
            "leaseStart",
            "nextDueDate",
            "paymentHistory",
            "tenant",
            "property",
        ]
        read_only_fields = fields

    @extend_schema_field(PropertySerializer)
    def get_property(self, tenancy) -> dict:
        prop = tenancy.property
        # Hand the annotated agent id to the embedded Property, so agentId is present
        # without another query.
        prop.active_agent_id = getattr(tenancy, "property_active_agent_id", None)
        return PropertySerializer(prop).data

    @extend_schema_field(PaymentEntrySerializer(many=True))
    def get_paymentHistory(self, tenancy) -> list:
        # Prefetched by selectors.tenancy_details(), already sorted by dueDate.
        return PaymentEntrySerializer(getattr(tenancy, "payment_history", []), many=True).data
