import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.common.models import OutboxEvent
from apps.notifications.models import Notification
from apps.properties.models import Property, PropertyAgentAssignment, PropertyTenantRequest
from apps.tenancies.models import Tenancy
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
PROPERTY_KEYS = {
    "id", "title", "address", "city", "state", "neighborhood", "photos", "bedrooms",
    "videos", "bathrooms", "sqft", "priceAnnual", "status", "landlordId", "occupancyRate", "featured",
    "agentId",
}  # fmt: skip


def new_property_body(**overrides):
    body = {
        "title": "Ocean View Duplex",
        "address": "12 Admiralty Way",
        "city": "Lagos",
        "state": "Lagos",
        "neighborhood": "Lekki Phase 1",
        "bedrooms": 4,
        "bathrooms": 3,
        "sqft": 2400,
        "priceAnnual": 12_000_000,
        "photos": ["https://images.example.com/1.jpg"],
    }
    body.update(overrides)
    return body


def ids(response):
    return {p["id"] for p in response.json()}


# --- Public reads ---------------------------------------------------------------------------


def test_anonymous_can_list_with_contract_shape(api_client):
    managed = AssignmentFactory().property
    PropertyFactory()

    response = api_client.get(f"{API}/properties")

    assert response.status_code == 200
    rows = {p["id"]: p for p in response.json()}
    assert all(set(p) == PROPERTY_KEYS for p in rows.values())
    assert rows[str(managed.id)]["agentId"] == str(managed.agent_assignments.get().agent_id)
    assert sum(p["agentId"] is None for p in rows.values()) == 1


def test_list_is_one_query_regardless_of_size(api_client, django_assert_num_queries):
    for _ in range(10):
        AssignmentFactory()
    with django_assert_num_queries(1):  # agentId comes from a correlated subquery
        response = api_client.get(f"{API}/properties")
    assert len(response.json()) == 10


def test_logged_in_users_see_the_full_public_catalogue(api_client, authenticate):
    """Public pages call GET /properties unfiltered while logged in; scoping would break them."""
    PropertyFactory.create_batch(2)
    authenticate(api_client, LandlordFactory())
    assert len(api_client.get(f"{API}/properties").json()) == 2


def test_retrieve_is_public_and_unknown_id_is_json_404(api_client):
    prop = PropertyFactory()
    assert api_client.get(f"{API}/properties/{prop.id}").json()["id"] == str(prop.id)
    missing = api_client.get(f"{API}/properties/01a0f8b9-4ac5-7117-afb8-11b7be1674b7")
    assert missing.status_code == 404
    assert missing.json() == {"message": "Not found."}


# --- Filters --------------------------------------------------------------------------------


def test_filter_city_is_case_insensitive_exact(api_client):
    lagos = PropertyFactory(city="Lagos")
    PropertyFactory(city="Abuja")
    PropertyFactory(city="Lagos Island")  # exact match, not "contains"
    assert ids(api_client.get(f"{API}/properties", {"city": "lagos"})) == {str(lagos.id)}


def test_filter_status_and_featured(api_client):
    listed = PropertyFactory(status="listed", featured=True)
    PropertyFactory(status="occupied", featured=True)
    PropertyFactory(status="listed", featured=False)
    response = api_client.get(f"{API}/properties", {"status": "listed", "featured": "true"})
    assert ids(response) == {str(listed.id)}


def test_available_filter_excludes_current_tenancies_and_unavailable_properties(api_client):
    available = PropertyFactory(status="listed")
    occupied_by_status = PropertyFactory(status="occupied")
    occupied_by_tenancy = PropertyFactory(status="listed")
    TenancyFactory(property=occupied_by_tenancy)
    PropertyFactory(status="unavailable")

    response = api_client.get(f"{API}/properties", {"available": "true"})

    assert ids(response) == {str(available.id)}


def test_filter_landlord(api_client):
    mine = PropertyFactory()
    PropertyFactory()
    response = api_client.get(f"{API}/properties", {"landlordId": str(mine.landlord_id)})
    assert ids(response) == {str(mine.id)}


def test_filter_agent_only_matches_active_assignments(api_client):
    agent = AgentFactory()
    active = AssignmentFactory(agent=agent).property
    former = PropertyFactory()
    AssignmentFactory(property=former, agent=agent, active=False, unassigned_at=timezone.now())
    AssignmentFactory(property=former)  # someone else manages it now

    response = api_client.get(f"{API}/properties", {"agentId": str(agent.id)})

    assert ids(response) == {str(active.id)}


SEARCH_CASES = {
    "ocean": {"title": "Ocean View Duplex", "neighborhood": "Ikoyi", "city": "Lagos"},
    "LEKKI": {"title": "Plain", "neighborhood": "Lekki Phase 1", "city": "Lagos"},
    "port harc": {"title": "Plain", "neighborhood": "GRA", "city": "Port Harcourt"},
}


@pytest.mark.parametrize(("term", "fields"), SEARCH_CASES.items())
def test_search_matches_title_neighborhood_or_city(api_client, term, fields):
    hit = PropertyFactory(**fields)
    PropertyFactory(title="Unrelated", neighborhood="Ikeja", city="Ibadan")
    assert ids(api_client.get(f"{API}/properties", {"search": term})) == {str(hit.id)}


def test_invalid_filter_value_is_400(api_client):
    response = api_client.get(f"{API}/properties", {"status": "demolished"})
    assert response.status_code == 400


# --- Create ---------------------------------------------------------------------------------


def test_landlord_creates_property_with_contract_defaults(api_client, authenticate):
    landlord = LandlordFactory()
    authenticate(api_client, landlord)
    someone_else = UserFactory()

    response = api_client.post(
        f"{API}/properties",
        new_property_body(landlordId=str(someone_else.id), occupancyRate=90),
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["landlordId"] == str(landlord.id)  # body's landlordId is not trusted
    assert body["status"] == "listed"
    assert body["occupancyRate"] == 0
    assert body["agentId"] is None
    assert body["featured"] is False


def test_square_footage_is_optional_on_create(api_client, authenticate):
    authenticate(api_client, LandlordFactory())
    body = new_property_body()
    body.pop("sqft")

    response = api_client.post(f"{API}/properties", body, format="json")

    assert response.status_code == 201
    assert response.json()["sqft"] is None


def test_square_footage_accepts_null_on_create(api_client, authenticate):
    authenticate(api_client, LandlordFactory())

    response = api_client.post(
        f"{API}/properties", new_property_body(sqft=None), format="json"
    )

    assert response.status_code == 201
    assert response.json()["sqft"] is None


@pytest.mark.parametrize(("role", "expected"), [("tenant", 403), ("agent", 403), (None, 401)])
def test_only_landlords_create(api_client, authenticate, role, expected):
    if role:
        authenticate(api_client, UserFactory(role=role))
    assert (
        api_client.post(f"{API}/properties", new_property_body(), format="json").status_code
        == expected
    )


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"photos": ["http://insecure.example.com/x.jpg"]}, "photos"),
        ({"priceAnnual": 0}, "priceAnnual"),
        ({"status": "sold"}, "status"),
        ({"bedrooms": -1}, "bedrooms"),
    ],
)
def test_create_validation(api_client, authenticate, overrides, field):
    authenticate(api_client, LandlordFactory())
    response = api_client.post(f"{API}/properties", new_property_body(**overrides), format="json")
    assert response.status_code == 400
    assert field in response.json()["errors"]


# --- Update ---------------------------------------------------------------------------------


def test_owner_patches_listing_including_occupancy(api_client, authenticate):
    prop = PropertyFactory()
    authenticate(api_client, prop.landlord)
    other = LandlordFactory()

    response = api_client.patch(
        f"{API}/properties/{prop.id}",
        {"title": "Renamed", "occupancyRate": 80, "landlordId": str(other.id), "agentId": None},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert response.json()["occupancyRate"] == 80
    prop.refresh_from_db()
    assert prop.landlord_id != other.id  # ownership can't be transferred via PATCH


def test_other_landlord_cannot_patch(api_client, authenticate):
    prop = PropertyFactory()
    authenticate(api_client, LandlordFactory())
    response = api_client.patch(f"{API}/properties/{prop.id}", {"title": "Mine now"}, format="json")
    assert response.status_code == 403


def test_full_put_and_delete_are_not_offered(api_client, authenticate):
    prop = PropertyFactory()
    authenticate(api_client, prop.landlord)
    assert (
        api_client.put(
            f"{API}/properties/{prop.id}", new_property_body(), format="json"
        ).status_code
        == 405
    )
    assert api_client.delete(f"{API}/properties/{prop.id}").status_code == 405


# --- Agent assignment -----------------------------------------------------------------------


def test_assign_agent_returns_assignment_and_property_reflects_it(
    api_client, authenticate, django_capture_on_commit_callbacks
):
    prop = PropertyFactory()
    agent = AgentFactory()
    authenticate(api_client, prop.landlord)

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.put(
            f"{API}/properties/{prop.id}/agent", {"agentId": str(agent.id)}, format="json"
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "propertyId", "agentId", "assignedAt", "active"}
    assert body["agentId"] == str(agent.id) and body["active"] is True
    assert api_client.get(f"{API}/properties/{prop.id}").json()["agentId"] == str(agent.id)
    outbox = OutboxEvent.objects.get(event_type="AgentAssigned")
    assert outbox.dispatched_at is not None  # delivered after commit
    assert outbox.payload["agent_id"] == str(agent.id)


def test_reassign_keeps_history_with_single_active_row(api_client, authenticate):
    first = AssignmentFactory()
    prop, second_agent = first.property, AgentFactory()
    authenticate(api_client, prop.landlord)

    api_client.put(
        f"{API}/properties/{prop.id}/agent", {"agentId": str(second_agent.id)}, format="json"
    )

    history = PropertyAgentAssignment.objects.filter(property=prop)
    assert history.count() == 2
    assert history.get(active=True).agent_id == second_agent.id
    first.refresh_from_db()
    assert first.active is False and first.unassigned_at is not None


def test_reassigning_same_agent_is_idempotent(api_client, authenticate):
    existing = AssignmentFactory()
    authenticate(api_client, existing.property.landlord)
    response = api_client.put(
        f"{API}/properties/{existing.property_id}/agent",
        {"agentId": str(existing.agent_id)},
        format="json",
    )
    assert response.json()["id"] == str(existing.id)
    assert PropertyAgentAssignment.objects.count() == 1
    assert not OutboxEvent.objects.exists()


@pytest.mark.parametrize("role", ["tenant", "landlord", "admin"])
def test_assigning_a_non_agent_is_400(api_client, authenticate, role):
    prop = PropertyFactory()
    authenticate(api_client, prop.landlord)
    not_an_agent = UserFactory(role=role)
    response = api_client.put(
        f"{API}/properties/{prop.id}/agent", {"agentId": str(not_an_agent.id)}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["message"] == "Agent id: No active agent with this id."


def test_non_owner_cannot_assign(api_client, authenticate):
    prop = PropertyFactory()
    authenticate(api_client, LandlordFactory())
    response = api_client.put(
        f"{API}/properties/{prop.id}/agent", {"agentId": str(AgentFactory().id)}, format="json"
    )
    assert response.status_code == 403
    assert not PropertyAgentAssignment.objects.exists()


def test_unassign_is_204_and_idempotent(api_client, authenticate):
    assignment = AssignmentFactory()
    prop = assignment.property
    authenticate(api_client, prop.landlord)

    assert api_client.delete(f"{API}/properties/{prop.id}/agent").status_code == 204
    assert api_client.delete(f"{API}/properties/{prop.id}/agent").status_code == 204
    assert api_client.get(f"{API}/properties/{prop.id}").json()["agentId"] is None
    assert OutboxEvent.objects.filter(event_type="AgentUnassigned").count() == 1


def test_database_rejects_two_active_assignments():
    """The invariant holds even for code that bypasses the service entirely."""
    prop = PropertyFactory()
    AssignmentFactory(property=prop)
    with pytest.raises(IntegrityError):
        PropertyAgentAssignment.objects.create(property=prop, agent=AgentFactory(), active=True)


def test_database_rejects_inactive_row_without_unassigned_at():
    with pytest.raises(IntegrityError):
        AssignmentFactory(active=False, unassigned_at=None)


def test_agent_tenant_assignment_requires_landlord_approval(api_client, authenticate):
    assignment = AssignmentFactory()
    tenant = UserFactory(role="tenant")
    authenticate(api_client, assignment.agent)

    response = api_client.post(
        f"{API}/properties/{assignment.property_id}/tenant-requests",
        {
            "action": "assign",
            "tenantId": str(tenant.id),
            "unit": "Flat 3B",
            "leaseStart": "2026-10-01",
            "nextDueDate": "2027-10-01",
        },
        format="json",
    )

    assert response.status_code == 201
    tenant_request = PropertyTenantRequest.objects.get(pk=response.json()["id"])
    assert tenant_request.status == PropertyTenantRequest.Status.PENDING
    assert not Tenancy.objects.filter(tenant=tenant, ended_at__isnull=True).exists()
    notification = Notification.objects.get(type=Notification.Type.TENANT_ASSIGNMENT_REQUEST)
    assert notification.recipient_id == assignment.property.landlord_id
    assert notification.data["tenantAssignmentRequestId"] == str(tenant_request.pk)

    authenticate(api_client, assignment.property.landlord)
    decision = api_client.post(
        f"{API}/tenant-requests/{tenant_request.pk}/decision",
        {"decision": "approve"},
        format="json",
    )

    assert decision.status_code == 200
    tenant_request.refresh_from_db()
    tenancy = Tenancy.objects.get(tenant=tenant, ended_at__isnull=True)
    assert tenant_request.status == PropertyTenantRequest.Status.APPROVED
    assert tenancy.property_id == assignment.property_id and tenancy.unit == "Flat 3B"


def test_only_owner_can_decide_tenant_request(api_client, authenticate):
    assignment = AssignmentFactory()
    tenant = UserFactory(role="tenant")
    tenant_request = PropertyTenantRequest.objects.create(
        property=assignment.property,
        tenant=tenant,
        requested_by=assignment.agent,
        action=PropertyTenantRequest.Action.ASSIGN,
        unit="Unit 1",
        lease_start="2026-10-01",
        next_due_date="2027-10-01",
    )
    authenticate(api_client, LandlordFactory())

    response = api_client.post(
        f"{API}/tenant-requests/{tenant_request.pk}/decision",
        {"decision": "approve"},
        format="json",
    )

    assert response.status_code == 403
    assert not Tenancy.objects.filter(tenant=tenant, ended_at__isnull=True).exists()


def test_rejecting_tenant_request_does_not_change_tenancy(api_client, authenticate):
    assignment = AssignmentFactory()
    tenant = UserFactory(role="tenant")
    tenant_request = PropertyTenantRequest.objects.create(
        property=assignment.property,
        tenant=tenant,
        requested_by=assignment.agent,
        action=PropertyTenantRequest.Action.ASSIGN,
        unit="Unit 1",
        lease_start="2026-10-01",
        next_due_date="2027-10-01",
    )
    authenticate(api_client, assignment.property.landlord)

    response = api_client.post(
        f"{API}/tenant-requests/{tenant_request.pk}/decision",
        {"decision": "reject"},
        format="json",
    )

    assert response.status_code == 200
    tenant_request.refresh_from_db()
    assert tenant_request.status == PropertyTenantRequest.Status.REJECTED
    assert not Tenancy.objects.filter(tenant=tenant, ended_at__isnull=True).exists()


def test_agent_candidate_search_matches_name_and_excludes_unavailable_tenants(api_client, authenticate):
    assignment = AssignmentFactory()
    matching = UserFactory(role="tenant", name="Nia Tenant")
    UserFactory(role="tenant", name="Other Person", email="nia.other@example.com")
    existing_tenancy = TenancyFactory()
    authenticate(api_client, assignment.agent)

    response = api_client.get(
        f"{API}/properties/{assignment.property_id}/tenant-candidates", {"search": "nia"}
    )

    assert response.status_code == 200
    assert response.json() == [{"id": str(matching.id), "name": "Nia Tenant"}]
    assert str(existing_tenancy.tenant_id) not in {row["id"] for row in response.json()}


def test_approved_tenant_removal_ends_current_tenancy(api_client, authenticate):
    tenancy = TenancyFactory()
    assignment = AssignmentFactory(property=tenancy.property)
    tenant_request = PropertyTenantRequest.objects.create(
        property=tenancy.property,
        tenant=tenancy.tenant,
        requested_by=assignment.agent,
        action=PropertyTenantRequest.Action.REMOVE,
    )
    authenticate(api_client, tenancy.property.landlord)

    response = api_client.post(
        f"{API}/tenant-requests/{tenant_request.pk}/decision",
        {"decision": "approve"},
        format="json",
    )

    assert response.status_code == 200
    tenancy.refresh_from_db()
    assert tenancy.ended_at is not None


# --- Top properties & assetsManagedCount ----------------------------------------------------


def test_top_ranks_by_occupancy_times_price_and_respects_limit(api_client, authenticate):
    agent = AgentFactory()
    low = PropertyFactory(occupancy_rate=50, price_annual=1_000_000)  # 50M
    high = PropertyFactory(occupancy_rate=90, price_annual=10_000_000)  # 900M
    mid = PropertyFactory(occupancy_rate=100, price_annual=2_000_000)  # 200M
    for prop in (low, high, mid):
        AssignmentFactory(property=prop, agent=agent)
    AssignmentFactory(property=PropertyFactory(occupancy_rate=100, price_annual=99_000_000))
    authenticate(api_client, agent)

    response = api_client.get(f"{API}/agents/{agent.id}/properties/top", {"limit": 2})

    assert [p["id"] for p in response.json()] == [str(high.id), str(mid.id)]
    assert api_client.get(f"{API}/agents/{agent.id}/properties/top").status_code == 200


def test_top_is_self_only_and_validates_limit(api_client, authenticate):
    me, other = AgentFactory(), AgentFactory()
    authenticate(api_client, me)
    assert api_client.get(f"{API}/agents/{other.id}/properties/top").status_code == 403
    bad = api_client.get(f"{API}/agents/{me.id}/properties/top", {"limit": 500})
    assert bad.status_code == 400


def test_me_reports_assets_managed_count_from_active_assignments(api_client, authenticate):
    agent = AgentFactory()
    AssignmentFactory.create_batch(2, agent=agent)
    AssignmentFactory(agent=agent, active=False, unassigned_at=timezone.now())
    authenticate(api_client, agent)
    assert api_client.get(f"{API}/auth/me").json()["assetsManagedCount"] == 2


def test_property_model_check_constraints():
    with pytest.raises(IntegrityError):
        Property.objects.bulk_create([PropertyFactory.build(occupancy_rate=101)])
