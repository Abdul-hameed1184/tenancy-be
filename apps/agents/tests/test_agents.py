import threading

import pytest
from django.db import connection
from django.utils import timezone

from apps.accounts.models import User
from apps.agents import services
from apps.agents.models import AgentProfile
from apps.audit.models import AuditLog
from apps.common.models import OutboxEvent
from tests.factories import AgentFactory, AssignmentFactory, LandlordFactory, UserFactory

API = "/api/v1"


def make_agent(status="unverified", trust=60, **profile):
    agent = AgentFactory()
    AgentProfile.objects.filter(user=agent).update(
        verification_status=status, trust_score=trust, **profile
    )
    agent.agent_profile.refresh_from_db()
    return agent


# --- Directory ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_public_list_with_assets_count_in_one_query(api_client, django_assert_num_queries):
    agents = [make_agent(passport_doc_url="https://docs.example.com/p.pdf") for _ in range(4)]
    AssignmentFactory.create_batch(2, agent=agents[0])
    AssignmentFactory(agent=agents[0], active=False, unassigned_at=timezone.now())

    with django_assert_num_queries(1):
        response = api_client.get(f"{API}/agents")

    rows = {a["id"]: a for a in response.json()}
    assert len(rows) == 4
    assert rows[str(agents[0].id)]["assetsManagedCount"] == 2
    assert all("passportDocUrl" not in a for a in rows.values())  # private for the public


@pytest.mark.django_db
def test_filter_by_verification_status(api_client):
    pending = make_agent("pending")
    make_agent("verified")
    response = api_client.get(f"{API}/agents", {"verificationStatus": "pending"})
    assert [a["id"] for a in response.json()] == [str(pending.id)]
    assert api_client.get(f"{API}/agents", {"verificationStatus": "bogus"}).status_code == 400


@pytest.mark.django_db
def test_verified_agent_filter_uses_email_verification_during_temporary_fix(api_client):
    email_verified = make_agent("unverified")
    User.objects.filter(pk=email_verified.pk).update(email_verified_at=timezone.now())
    legacy_profile_verified = make_agent("verified")
    User.objects.filter(pk=legacy_profile_verified.pk).update(email_verified_at=None)

    response = api_client.get(f"{API}/agents", {"verificationStatus": "verified"})

    assert [agent["id"] for agent in response.json()] == [str(email_verified.id)]


@pytest.mark.django_db
def test_detail_is_public_and_non_agents_are_404(api_client):
    agent = make_agent()
    body = api_client.get(f"{API}/agents/{agent.id}").json()
    assert body["role"] == "agent" and "trustScore" in body
    assert api_client.get(f"{API}/agents/{LandlordFactory().id}").status_code == 404


@pytest.mark.django_db
def test_agent_and_admin_see_private_document_fields(api_client, authenticate):
    agent = make_agent(passport_doc_url="https://docs.example.com/p.pdf")
    for viewer in (agent, UserFactory(role="admin")):
        authenticate(api_client, viewer)
        body = api_client.get(f"{API}/agents/{agent.id}").json()
        assert body["passportDocUrl"] == "https://docs.example.com/p.pdf"
    authenticate(api_client, LandlordFactory())
    assert "passportDocUrl" not in api_client.get(f"{API}/agents/{agent.id}").json()


# --- Admin verification ---------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_lists_only_pending(api_client, authenticate):
    pending = make_agent("pending")
    make_agent("unverified")
    authenticate(api_client, UserFactory(role="admin"))
    assert [a["id"] for a in api_client.get(f"{API}/admin/verifications").json()] == [
        str(pending.id)
    ]


@pytest.mark.django_db
@pytest.mark.parametrize(("start", "expected"), [(40, 80), (95, 95)])
def test_verifying_raises_trust_to_at_least_80(api_client, authenticate, start, expected):
    agent = make_agent("pending", trust=start)
    admin = UserFactory(role="admin")
    authenticate(api_client, admin)

    response = api_client.post(
        f"{API}/admin/verifications/{agent.id}", {"decision": "verified"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["verificationStatus"] == "verified"
    assert response.json()["trustScore"] == expected
    profile = AgentProfile.objects.get(user=agent)
    assert profile.reviewed_by == admin and profile.reviewed_at is not None
    assert AuditLog.objects.filter(action="AGENT_VERIFIED", entity_id=str(agent.id)).exists()
    assert OutboxEvent.objects.filter(event_type="AgentVerified").exists()


@pytest.mark.django_db
def test_rejecting_keeps_trust_score(api_client, authenticate):
    agent = make_agent("pending", trust=40)
    authenticate(api_client, UserFactory(role="admin"))
    body = api_client.post(
        f"{API}/admin/verifications/{agent.id}", {"decision": "rejected"}, format="json"
    ).json()
    assert body["verificationStatus"] == "rejected" and body["trustScore"] == 40
    assert AuditLog.objects.filter(action="AGENT_VERIFICATION_REJECTED").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["unverified", "verified", "rejected"])
def test_only_pending_can_be_decided(api_client, authenticate, status):
    agent = make_agent(status)
    authenticate(api_client, UserFactory(role="admin"))
    response = api_client.post(
        f"{API}/admin/verifications/{agent.id}", {"decision": "verified"}, format="json"
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_invalid_decision_and_unknown_agent(api_client, authenticate):
    agent = make_agent("pending")
    authenticate(api_client, UserFactory(role="admin"))
    bad = api_client.post(
        f"{API}/admin/verifications/{agent.id}", {"decision": "pending"}, format="json"
    )
    assert bad.status_code == 400
    missing = api_client.post(
        f"{API}/admin/verifications/{LandlordFactory().id}", {"decision": "verified"}, format="json"
    )
    assert missing.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["landlord", "agent", "tenant"])
def test_non_admins_cannot_verify(api_client, authenticate, role):
    agent = make_agent("pending")
    authenticate(api_client, UserFactory(role=role))
    assert api_client.get(f"{API}/admin/verifications").status_code == 403
    response = api_client.post(
        f"{API}/admin/verifications/{agent.id}", {"decision": "verified"}, format="json"
    )
    assert response.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_two_admins_deciding_at_once_only_one_applies():
    agent = make_agent("pending", trust=10)
    admins = [UserFactory(role="admin"), UserFactory(role="admin")]
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker(admin, decision):
        try:
            barrier.wait()
            services.decide_verification(agent_id=agent.pk, decision=decision, admin=admin)
            outcomes.append(decision)
        except Exception as exc:
            outcomes.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=worker, args=(admins[0], "verified")),
        threading.Thread(target=worker, args=(admins[1], "rejected")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert "Conflict" in outcomes and len(outcomes) == 2
    final = AgentProfile.objects.get(user=agent).verification_status
    assert final in outcomes  # the winner's decision stuck
    assert OutboxEvent.objects.count() == 1
