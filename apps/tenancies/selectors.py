from django.db.models import Exists, OuterRef, Prefetch, QuerySet, Subquery

from apps.accounts.models import User
from apps.properties.selectors import active_assignments

from .models import Tenancy


def tenancy_details() -> QuerySet[Tenancy]:
    """
    Current tenancies with everything TenancyDetail embeds, in two queries per page:

    - tenant, property:     select_related (JOIN; both are to-one)
    - property's agentId:   correlated subquery (a *filtered* relation, so it can't be
                            select_related)
    - paymentHistory:       prefetch_related, one extra "WHERE tenancy_id IN (...)" query
                            for the whole page (to-many: a JOIN would multiply rows)
    """
    from apps.payments.models import PaymentEntry

    agent = active_assignments().filter(property=OuterRef("property_id")).values("agent_id")[:1]
    return (
        Tenancy.objects.filter(ended_at__isnull=True)
        .select_related("tenant", "property")
        .annotate(property_active_agent_id=Subquery(agent))
        .prefetch_related(
            Prefetch(
                "payments",
                queryset=PaymentEntry.objects.order_by("due_date", "logged_at"),
                to_attr="payment_history",
            )
        )
    )


def visible_to(user: User) -> QuerySet[Tenancy]:
    qs = tenancy_details()
    if user.is_admin:
        return qs
    if user.is_landlord:
        return qs.filter(property__landlord=user)
    if user.is_agent:
        # EXISTS rather than a JOIN: a semi-join can't duplicate rows, and it matches only
        # *active* management. A former agent loses access the moment they're replaced.
        return qs.filter(
            Exists(active_assignments().filter(agent=user, property=OuterRef("property_id")))
        )
    if user.is_tenant:
        return qs.filter(tenant=user)
    return qs.none()
