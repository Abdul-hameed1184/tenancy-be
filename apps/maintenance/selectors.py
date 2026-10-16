from django.db.models import Exists, OuterRef, QuerySet

from apps.accounts.models import User
from apps.properties.selectors import active_assignments

from .models import MaintenanceRequest


def visible_to(user: User) -> QuerySet[MaintenanceRequest]:
    qs = MaintenanceRequest.objects.order_by("-reported_at")
    if user.is_admin:
        return qs
    if user.is_landlord:
        return qs.filter(property__landlord=user)
    if user.is_agent:
        return qs.filter(
            Exists(active_assignments().filter(agent=user, property=OuterRef("property_id")))
        )
    if user.is_tenant:
        return qs.filter(tenant=user)
    return qs.none()
