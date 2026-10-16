from django_filters import rest_framework as filters

from apps.properties.selectors import active_assignments

from .models import MaintenanceRequest


class MaintenanceFilter(filters.FilterSet):
    agentId = filters.UUIDFilter(method="filter_agent")
    tenantId = filters.UUIDFilter(field_name="tenant_id")
    propertyId = filters.UUIDFilter(field_name="property_id")
    status = filters.ChoiceFilter(choices=MaintenanceRequest.Status.choices)

    class Meta:
        model = MaintenanceRequest
        fields = ["agentId", "tenantId", "propertyId", "status"]

    def filter_agent(self, queryset, name, value):
        managed = active_assignments().filter(agent_id=value).values("property_id")
        return queryset.filter(property_id__in=managed)
