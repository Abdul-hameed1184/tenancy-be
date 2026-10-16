from django.db.models import F, OuterRef, QuerySet, Subquery

from .models import Property, PropertyAgentAssignment


def active_assignments() -> QuerySet[PropertyAgentAssignment]:
    return PropertyAgentAssignment.objects.filter(active=True)


def with_active_agent(qs: QuerySet[Property]) -> QuerySet[Property]:
    """
    Annotate `active_agent_id`, which every Property response needs as `agentId`.

    A correlated subquery keeps it to one SQL statement for any list size; resolving it per
    row in the serializer would be one extra query per property (N+1). The partial unique
    index guarantees the subquery yields at most one row.
    """
    agent = active_assignments().filter(property=OuterRef("pk")).values("agent_id")[:1]
    return qs.annotate(active_agent_id=Subquery(agent))


def property_catalogue() -> QuerySet[Property]:
    """
    Property reads are a public catalogue: the contract marks GET /properties[/:id] as
    public for every role, and the public pages call them unfiltered even when logged in.
    Ownership is enforced on writes, and on the private data hanging off a property
    (tenancies, payments, maintenance).
    """
    return with_active_agent(Property.objects.all())


def managed_by(agent_id) -> QuerySet[Property]:
    """Properties with an *active* assignment to this agent (the contract's agentId)."""
    return Property.objects.filter(
        agent_assignments__active=True, agent_assignments__agent_id=agent_id
    )


def top_for_agent(agent_id, limit: int) -> QuerySet[Property]:
    """The agent's properties ranked by occupancyRate * priceAnnual, computed in SQL."""
    return (
        with_active_agent(managed_by(agent_id))
        .annotate(performance=F("occupancy_rate") * F("price_annual"))
        .order_by("-performance", "-created_at")[:limit]
    )
