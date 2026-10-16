import datetime

import pytest
from django.db import IntegrityError
from django.utils import timezone

from tests.factories import (
    AgentFactory,
    AssignmentFactory,
    LandlordFactory,
    PropertyFactory,
    TenancyFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

API = "/api/v1"
DETAIL_KEYS = {
    "id", "tenantId", "propertyId", "unit", "leaseStart", "nextDueDate", "paymentHistory",
    "tenant", "property",
}  # fmt: skip


def ids(response):
    return {t["id"] for t in response.json()}


@pytest.fixture
def portfolio():
    """Two landlords; landlord A's property is managed by agent A."""
    landlord_a, landlord_b = LandlordFactory(), LandlordFactory()
    agent_a = AgentFactory()
    prop_a = PropertyFactory(landlord=landlord_a)
    AssignmentFactory(property=prop_a, agent=agent_a)
    prop_b = PropertyFactory(landlord=landlord_b)
    return {
        "landlord_a": landlord_a,
        "landlord_b": landlord_b,
        "agent_a": agent_a,
        "tenancy_a": TenancyFactory(property=prop_a),
        "tenancy_b": TenancyFactory(property=prop_b),
    }


# --- Shape ----------------------------------------------------------------------------------


def test_detail_shape_embeds_tenant_property_and_agent(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["landlord_a"])
    tenancy = portfolio["tenancy_a"]

    body = api_client.get(f"{API}/tenancies/{tenancy.id}").json()

    assert set(body) == DETAIL_KEYS
    assert body["tenantId"] == str(tenancy.tenant_id) == body["tenant"]["id"]
    assert body["propertyId"] == str(tenancy.property_id) == body["property"]["id"]
    assert body["property"]["agentId"] == str(portfolio["agent_a"].id)
    assert body["leaseStart"] == "2025-10-01T00:00:00.000Z"
    assert body["nextDueDate"] == "2026-10-01T00:00:00.000Z"
    assert body["paymentHistory"] == []


def test_embedded_property_without_agent_has_null_agent_id(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["landlord_b"])
    body = api_client.get(f"{API}/tenancies/{portfolio['tenancy_b'].id}").json()
    assert body["property"]["agentId"] is None


# --- Scope ----------------------------------------------------------------------------------


def test_landlord_sees_only_tenancies_on_own_properties(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["landlord_a"])
    assert ids(api_client.get(f"{API}/tenancies")) == {str(portfolio["tenancy_a"].id)}
    other = api_client.get(f"{API}/tenancies/{portfolio['tenancy_b'].id}")
    assert other.status_code == 404


def test_agent_sees_only_actively_managed_properties(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["agent_a"])
    assert ids(api_client.get(f"{API}/tenancies")) == {str(portfolio["tenancy_a"].id)}


def test_replaced_agent_loses_access_immediately(api_client, authenticate, portfolio):
    agent = portfolio["agent_a"]
    assignment = agent.agent_assignments.get()
    assignment.active, assignment.unassigned_at = False, timezone.now()
    assignment.save()
    authenticate(api_client, agent)
    assert api_client.get(f"{API}/tenancies").json() == []


def test_forged_filters_cannot_widen_scope(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["landlord_a"])
    forged = api_client.get(
        f"{API}/tenancies", {"landlordId": str(portfolio["landlord_b"].id)}
    ).json()
    assert forged == []
    by_property = api_client.get(
        f"{API}/tenancies", {"propertyId": str(portfolio["tenancy_b"].property_id)}
    ).json()
    assert by_property == []


def test_filters_narrow_within_scope(api_client, authenticate, portfolio):
    authenticate(api_client, UserFactory(role="admin"))
    agent_filtered = api_client.get(f"{API}/tenancies", {"agentId": str(portfolio["agent_a"].id)})
    assert ids(agent_filtered) == {str(portfolio["tenancy_a"].id)}
    by_landlord = api_client.get(
        f"{API}/tenancies", {"landlordId": str(portfolio["landlord_b"].id)}
    )
    assert ids(by_landlord) == {str(portfolio["tenancy_b"].id)}


def test_tenants_cannot_list_tenancies(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["tenancy_a"].tenant)
    assert api_client.get(f"{API}/tenancies").status_code == 403


def test_anonymous_gets_401(api_client):
    assert api_client.get(f"{API}/tenancies").status_code == 401


def test_ended_tenancies_are_not_listed(api_client, authenticate, portfolio):
    TenancyFactory(property=portfolio["tenancy_a"].property, ended_at=timezone.now())
    authenticate(api_client, portfolio["landlord_a"])
    assert len(api_client.get(f"{API}/tenancies").json()) == 1


# --- Query efficiency -----------------------------------------------------------------------


def test_list_query_count_does_not_grow_with_rows(
    api_client, authenticate, django_assert_num_queries
):
    landlord, agent = LandlordFactory(), AgentFactory()
    for _ in range(8):
        prop = PropertyFactory(landlord=landlord)
        AssignmentFactory(property=prop, agent=agent)
        TenancyFactory(property=prop)
    authenticate(api_client, landlord)

    # 1: authenticate. 2: tenancies JOIN tenant JOIN property + agent subquery.
    # 3: payment history for the whole page, WHERE tenancy_id IN (...).
    with django_assert_num_queries(3):
        response = api_client.get(f"{API}/tenancies")
    assert len(response.json()) == 8
    assert all(t["property"]["agentId"] == str(agent.id) for t in response.json())


# --- Tenant's own tenancy -------------------------------------------------------------------


def test_tenant_reads_own_tenancy(api_client, authenticate, portfolio):
    tenancy = portfolio["tenancy_a"]
    authenticate(api_client, tenancy.tenant)
    response = api_client.get(f"{API}/tenants/{tenancy.tenant_id}/tenancy")
    assert response.status_code == 200
    assert response.json()["id"] == str(tenancy.id)


def test_tenant_cannot_read_someone_elses_tenancy(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["tenancy_a"].tenant)
    other = portfolio["tenancy_b"].tenant_id
    assert api_client.get(f"{API}/tenants/{other}/tenancy").status_code == 403


def test_tenant_without_tenancy_gets_404_with_message(api_client, authenticate):
    tenant = UserFactory(role="tenant")
    authenticate(api_client, tenant)
    response = api_client.get(f"{API}/tenants/{tenant.id}/tenancy")
    assert response.status_code == 404
    assert response.json() == {"message": "You don't have a current tenancy."}


def test_only_tenants_use_the_tenant_endpoint(api_client, authenticate, portfolio):
    authenticate(api_client, portfolio["landlord_a"])
    path = f"{API}/tenants/{portfolio['tenancy_a'].tenant_id}/tenancy"
    assert api_client.get(path).status_code == 403


# --- Database integrity ---------------------------------------------------------------------


def test_tenant_cannot_hold_two_current_tenancies():
    first = TenancyFactory()
    with pytest.raises(IntegrityError):
        TenancyFactory(tenant=first.tenant)


def test_unit_cannot_have_two_current_tenants():
    first = TenancyFactory()
    with pytest.raises(IntegrityError):
        TenancyFactory(property=first.property, unit=first.unit)


def test_ended_tenancy_frees_tenant_and_unit():
    first = TenancyFactory(ended_at=timezone.now())
    TenancyFactory(tenant=first.tenant, property=first.property, unit=first.unit)


def test_next_due_date_cannot_precede_lease_start():
    with pytest.raises(IntegrityError):
        TenancyFactory(
            lease_start=datetime.date(2026, 1, 1), next_due_date=datetime.date(2025, 12, 31)
        )


def test_model_validation_rejects_non_tenant_user():
    from django.core.exceptions import ValidationError

    tenancy = TenancyFactory.build(tenant=LandlordFactory(), property=PropertyFactory())
    with pytest.raises(ValidationError):
        tenancy.full_clean()
