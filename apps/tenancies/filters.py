from django_filters import rest_framework as filters

from apps.properties.selectors import active_assignments

from .models import Tenancy


class TenancyFilter(filters.FilterSet):
    """Applied *inside* the caller's scope (see selectors.visible_to), so ids can only narrow."""

    agentId = filters.UUIDFilter(method="filter_agent")
    landlordId = filters.UUIDFilter(field_name="property__landlord_id")
    propertyId = filters.UUIDFilter(field_name="property_id")

    class Meta:
        model = Tenancy
        fields = ["agentId", "landlordId", "propertyId"]

    def filter_agent(self, queryset, name, value):
        # The property's *active* managing agent.
        managed = active_assignments().filter(agent_id=value).values("property_id")
        return queryset.filter(property_id__in=managed)
