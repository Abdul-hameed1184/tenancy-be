"""One test per statistic, each with data that would be miscounted by a wrong filter."""

import datetime
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.dashboards import selectors
from apps.properties.models import Property
from apps.properties.models import PropertyAgentAssignment as Assignment
from tests.factories import (
    AgentFactory,
    AssignmentFactory,
    InspectionFactory,
    LandlordFactory,
    MaintenanceFactory,
    PaymentFactory,
    PropertyFactory,
    TenancyFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
LAGOS = ZoneInfo("Africa/Lagos")


def lagos_today():
    return timezone.now().astimezone(LAGOS).date()


# --- Agent ----------------------------------------------------------------------------------


@pytest.fixture
def agent_world():
    agent = AgentFactory()
    managed = [PropertyFactory(), PropertyFactory()]
    for prop in managed:
        AssignmentFactory(property=prop, agent=agent)
    former = PropertyFactory()  # previously managed: must never count
    AssignmentFactory(property=former, agent=agent, active=False, unassigned_at=timezone.now())
    return agent, managed, former


def test_active_properties_and_new_this_month(agent_world):
    agent, managed, _ = agent_world
    month_start = datetime.datetime.combine(
        lagos_today().replace(day=1), datetime.time.min, tzinfo=LAGOS
    )
    Assignment.objects.filter(property=managed[0]).update(
        assigned_at=month_start - datetime.timedelta(days=3)
    )
    stats = selectors.agent_stats(agent)
    assert stats["activeProperties"] == 2
    assert stats["activePropertiesNewThisMonth"] == 1


def test_total_tenants_and_high_priority(agent_world):
    agent, managed, former = agent_world
    today = lagos_today()
    TenancyFactory(
        property=managed[0],
        lease_start=today - datetime.timedelta(days=400),
        next_due_date=today - datetime.timedelta(days=1),
    )  # overdue -> high
    TenancyFactory(
        property=managed[1],
        lease_start=today - datetime.timedelta(days=360),
        next_due_date=today + datetime.timedelta(days=7),
    )  # due in 7 -> high
    TenancyFactory(
        property=managed[1],
        lease_start=today - datetime.timedelta(days=100),
        next_due_date=today + datetime.timedelta(days=8),
    )  # not yet
    TenancyFactory(property=managed[0], ended_at=timezone.now())  # ended: excluded
    TenancyFactory(property=former)  # not managed: excluded
    stats = selectors.agent_stats(agent)
    assert stats["totalTenants"] == 3
    assert stats["totalTenantsHighPriority"] == 2


def test_maintenance_pending_and_high(agent_world):
    agent, managed, former = agent_world
    MaintenanceFactory(property=managed[0], priority="high")
    MaintenanceFactory(property=managed[1], priority="low", status="in_progress")
    MaintenanceFactory(property=managed[0], priority="high", status="completed",
                       completed_at=timezone.now())  # fmt: skip
    MaintenanceFactory(property=former, priority="high")
    stats = selectors.agent_stats(agent)
    assert stats["maintenancePending"] == 2
    assert stats["maintenanceHighPriority"] == 1


def test_upcoming_inspections_and_today(agent_world):
    agent, _, _ = agent_world
    today_noon = datetime.datetime.combine(lagos_today(), datetime.time(12), tzinfo=LAGOS)
    InspectionFactory(agent=agent, scheduled_at=today_noon)
    InspectionFactory(
        agent=agent, status="confirmed", scheduled_at=today_noon + datetime.timedelta(days=2)
    )
    InspectionFactory(agent=agent, status="completed", scheduled_at=today_noon)
    InspectionFactory(
        agent=agent, status="cancelled", cancelled_at=timezone.now(), scheduled_at=today_noon
    )
    InspectionFactory(scheduled_at=today_noon)  # someone else's
    stats = selectors.agent_stats(agent)
    assert stats["upcomingInspections"] == 2
    assert stats["inspectionsScheduledToday"] == 1


def test_agent_stats_uses_constant_queries(agent_world, django_assert_num_queries):
    agent, _, _ = agent_world
    with django_assert_num_queries(4):
        selectors.agent_stats(agent)


def test_empty_agent_has_zero_stats():
    stats = selectors.agent_stats(AgentFactory())
    assert set(stats.values()) == {0}


# --- Landlord -------------------------------------------------------------------------------


@pytest.fixture
def landlord_world():
    landlord = LandlordFactory()
    long_ago = timezone.now() - datetime.timedelta(days=90)
    a = PropertyFactory(
        landlord=landlord,
        city="Lagos",
        status="occupied",
        price_annual=10_000_000,
        occupancy_rate=100,
        created_at=long_ago,
    )
    b = PropertyFactory(
        landlord=landlord,
        city="lagos",
        status="listed",
        price_annual=4_000_000,
        occupancy_rate=50,
        created_at=long_ago,
    )
    c = PropertyFactory(
        landlord=landlord,
        city="Abuja",
        status="unavailable",
        price_annual=6_000_000,
        occupancy_rate=25,
    )  # created this month
    PropertyFactory(price_annual=99_000_000, status="occupied")  # another landlord
    return landlord, (a, b, c)


def test_portfolio_value_and_change(landlord_world):
    landlord, _ = landlord_world
    stats = selectors.landlord_stats(landlord)
    assert stats["totalPortfolioValue"] == 20_000_000
    # baseline excludes the property created this month: (20M - 14M) / 14M
    assert stats["portfolioValueChangePct"] == round(6 / 14 * 100, 1)


def test_annual_revenue_counts_paid_receipts_this_year(landlord_world):
    landlord, (property, *_rest) = landlord_world
    tenancy = TenancyFactory(property=property)
    today = lagos_today()
    PaymentFactory(
        tenancy=tenancy,
        amount=10_000_000,
        due_date=datetime.date(today.year, 1, 10),
        paid_date=today,
    )
    assert selectors.landlord_stats(landlord)["annualRevenue"] == 10_000_000


def test_occupancy_vacancy_assets_and_cities(landlord_world):
    landlord, (occupied_property, *_rest) = landlord_world
    TenancyFactory(property=occupied_property)
    stats = selectors.landlord_stats(landlord)
    assert stats["occupancyRatePct"] == round(1 / 3 * 100)
    assert stats["vacantUnits"] == 2
    assert stats["occupiedProperties"] == 1
    assert stats["occupiedUnits"] == 1
    assert stats["managedAssets"] == 3
    assert stats["citiesCount"] == 2  # "Lagos" and "lagos" are one city


def test_collection_rate_over_this_years_ledger(landlord_world):
    landlord, (a, *_rest) = landlord_world
    tenancy = TenancyFactory(property=a)
    this_year = lagos_today().year
    PaymentFactory(tenancy=tenancy, amount=3_000_000, due_date=datetime.date(this_year, 1, 10))
    PaymentFactory(tenancy=tenancy, amount=1_000_000, status="due", paid_date=None,
                   due_date=datetime.date(this_year, 2, 10))  # fmt: skip
    PaymentFactory(tenancy=tenancy, amount=9_000_000, due_date=datetime.date(this_year - 1, 3, 1))
    assert selectors.landlord_stats(landlord)["collectionRatePct"] == 75


def test_landlord_without_anything(db):
    stats = selectors.landlord_stats(LandlordFactory())
    assert stats["totalPortfolioValue"] == 0 and stats["portfolioValueChangePct"] == 0
    assert stats["collectionRatePct"] == 100 and stats["occupancyRatePct"] == 0


def test_landlord_stats_uses_constant_queries(landlord_world, django_assert_num_queries):
    with django_assert_num_queries(3):
        selectors.landlord_stats(landlord_world[0])


# --- Endpoints ------------------------------------------------------------------------------


def test_agent_endpoint_is_self_or_admin(api_client, authenticate):
    agent = AgentFactory()
    authenticate(api_client, agent)
    body = api_client.get(f"/api/v1/agents/{agent.id}/stats").json()
    assert set(body) == {
        "activeProperties", "activePropertiesNewThisMonth", "totalTenants",
        "totalTenantsHighPriority", "maintenancePending", "maintenanceHighPriority",
        "upcomingInspections", "inspectionsScheduledToday",
    }  # fmt: skip
    assert api_client.get(f"/api/v1/agents/{AgentFactory().id}/stats").status_code == 403
    authenticate(api_client, UserFactory(role="admin"))
    assert api_client.get(f"/api/v1/agents/{agent.id}/stats").status_code == 200
    assert api_client.get(f"/api/v1/agents/{LandlordFactory().id}/stats").status_code == 404


def test_landlord_endpoint_is_self_or_admin(api_client, authenticate, landlord_world):
    landlord, _ = landlord_world
    authenticate(api_client, landlord)
    assert api_client.get(f"/api/v1/landlords/{landlord.id}/stats").json()["managedAssets"] == 3
    assert api_client.get(f"/api/v1/landlords/{LandlordFactory().id}/stats").status_code == 403
    authenticate(api_client, UserFactory(role="tenant"))
    assert api_client.get(f"/api/v1/landlords/{landlord.id}/stats").status_code == 403


def test_stats_are_cached_briefly(api_client, authenticate, landlord_world):
    landlord, _ = landlord_world
    authenticate(api_client, landlord)
    first = api_client.get(f"/api/v1/landlords/{landlord.id}/stats").json()
    Property.objects.filter(landlord=landlord).update(occupancy_rate=0)
    assert api_client.get(f"/api/v1/landlords/{landlord.id}/stats").json() == first  # 30s TTL
