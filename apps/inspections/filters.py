from django_filters import rest_framework as filters

from .models import Inspection


class InspectionFilter(filters.FilterSet):
    agentId = filters.UUIDFilter(field_name="agent_id")
    tenantId = filters.UUIDFilter(field_name="tenant_id")
    propertyId = filters.UUIDFilter(field_name="property_id")
    status = filters.ChoiceFilter(choices=Inspection.Status.choices)

    class Meta:
        model = Inspection
        fields = ["agentId", "tenantId", "propertyId", "status"]
