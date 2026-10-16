from django.db.models import Exists, OuterRef, Q
from django_filters import rest_framework as filters

from .models import Property
from .selectors import active_assignments
from apps.tenancies.models import Tenancy


class PropertyFilter(filters.FilterSet):
    """Query parameters from the contract. Unset filters are simply absent."""

    city = filters.CharFilter(field_name="city", lookup_expr="iexact")
    status = filters.ChoiceFilter(choices=Property.Status.choices)
    available = filters.BooleanFilter(method="filter_available")
    featured = filters.BooleanFilter()
    landlordId = filters.UUIDFilter(field_name="landlord_id")
    agentId = filters.UUIDFilter(method="filter_agent")
    search = filters.CharFilter(method="filter_search")

    class Meta:
        model = Property
        fields = ["city", "status", "featured", "available", "landlordId", "agentId", "search"]

    def filter_available(self, queryset, name, value):
        if not value:
            return queryset
        current_tenancy = Tenancy.objects.filter(
            property_id=OuterRef("pk"), ended_at__isnull=True
        )
        return (
            queryset.filter(status=Property.Status.LISTED)
            .annotate(has_current_tenancy=Exists(current_tenancy))
            .filter(has_current_tenancy=False)
        )

    def filter_agent(self, queryset, name, value):
        # "properties with an active assignment to this agent": a semi-join (WHERE id IN
        # ...), so a property can never appear twice regardless of history rows.
        managed = active_assignments().filter(agent_id=value).values("property_id")
        return queryset.filter(pk__in=managed)

    def filter_search(self, queryset, name, value):
        term = value.strip()
        if not term:
            return queryset
        return queryset.filter(
            Q(title__icontains=term) | Q(neighborhood__icontains=term) | Q(city__icontains=term)
        )
