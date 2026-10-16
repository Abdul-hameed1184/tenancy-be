from django.db.models import Count, Q, QuerySet

from apps.accounts.models import User
from apps.properties.selectors import active_assignments


def assets_managed_count(agent) -> int:
    """`assetsManagedCount`: derived from active assignments, never stored, so it can't drift."""
    return active_assignments().filter(agent=agent).count()


def agent_profiles() -> QuerySet[User]:
    """
    Agents as AgentProfile rows: User JOIN agent_profile, with assetsManagedCount as
    COUNT(...) FILTER (WHERE active) in the same query, so any list size is one query.
    """
    return (
        User.objects.filter(role=User.Role.AGENT, is_active=True, agent_profile__isnull=False)
        .select_related("agent_profile")
        .annotate(
            assets_managed_count=Count(
                "agent_assignments", filter=Q(agent_assignments__active=True)
            )
        )
        .order_by("-agent_profile__trust_score", "name")
    )
