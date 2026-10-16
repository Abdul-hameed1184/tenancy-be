from django.db.models import QuerySet

from apps.accounts.models import User

from .models import Inspection


def visible_to(user: User) -> QuerySet[Inspection]:
    """
    Agents see the inspections assigned to them (the booking captured the then-active
    agent), tenants their own bookings, landlords those on their properties.
    """
    qs = Inspection.objects.order_by("scheduled_at")
    if user.is_admin:
        return qs
    if user.is_agent:
        return qs.filter(agent=user)
    if user.is_tenant:
        return qs.filter(tenant=user)
    if user.is_landlord:
        return qs.filter(property__landlord=user)
    return qs.none()
