from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.common.cache import cached
from apps.common.permissions import HasRole, ensure_self

from . import selectors

TAGS = ["dashboards"]
# Short TTL instead of event-driven invalidation: stats depend on too many tables to track
# every write, and 30 seconds of staleness on a dashboard is acceptable.
STATS_TTL = 30

AgentStats = inline_serializer(
    "AgentStats",
    {
        name: serializers.IntegerField()
        for name in (
            "activeProperties",
            "activePropertiesNewThisMonth",
            "totalTenants",
            "totalTenantsHighPriority",
            "maintenancePending",
            "maintenanceHighPriority",
            "upcomingInspections",
            "inspectionsScheduledToday",
        )
    },
)
LandlordStats = inline_serializer(
    "LandlordStats",
    {
        "totalPortfolioValue": serializers.IntegerField(),
        "portfolioValueChangePct": serializers.FloatField(),
        "annualRevenue": serializers.IntegerField(),
        "collectionRatePct": serializers.IntegerField(),
        "occupancyRatePct": serializers.IntegerField(),
        "vacantUnits": serializers.IntegerField(),
        "occupiedUnits": serializers.IntegerField(),
        "occupiedProperties": serializers.IntegerField(),
        "managedAssets": serializers.IntegerField(),
        "citiesCount": serializers.IntegerField(),
    },
)


def _subject(request, user_id, role):
    ensure_self(request.user, user_id, allow_admin=True, what="dashboard")
    subject = User.objects.filter(pk=user_id, role=role, is_active=True).first()
    if subject is None:
        raise NotFound("Not found.")
    return subject


class AgentStatsView(APIView):
    permission_classes = [HasRole("agent", "admin")]

    @extend_schema(tags=TAGS, responses={200: AgentStats})
    def get(self, request, agent_id):
        agent = _subject(request, agent_id, User.Role.AGENT)
        return Response(
            cached(
                "stats", "agent", {"id": agent.pk}, STATS_TTL, lambda: selectors.agent_stats(agent)
            )
        )


class LandlordStatsView(APIView):
    permission_classes = [HasRole("landlord", "admin")]

    @extend_schema(tags=TAGS, responses={200: LandlordStats})
    def get(self, request, landlord_id):
        landlord = _subject(request, landlord_id, User.Role.LANDLORD)
        return Response(
            cached(
                "stats",
                "landlord",
                {"id": landlord.pk},
                STATS_TTL,
                lambda: selectors.landlord_stats(landlord),
            )
        )
