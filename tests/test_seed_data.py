import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User
from apps.payments.models import PaymentEntry
from apps.properties.models import Property

pytestmark = pytest.mark.django_db


def test_seed_is_idempotent_and_creates_every_role(settings):
    settings.DEBUG = True
    call_command("seed_data")
    first = (User.objects.count(), Property.objects.count(), PaymentEntry.objects.count())
    call_command("seed_data")  # second run: same ids, no duplicates, ledger untouched
    assert (User.objects.count(), Property.objects.count(), PaymentEntry.objects.count()) == first
    assert set(User.objects.values_list("role", flat=True)) == {"admin", "landlord", "agent",
                                                                "tenant"}  # fmt: skip


def test_seeded_accounts_can_log_in(settings, api_client):
    settings.DEBUG = True
    call_command("seed_data")
    for email in ("admin@pleet.test", "landlord@pleet.test", "agent@pleet.test",
                  "tenant@pleet.test"):  # fmt: skip
        response = api_client.post(
            "/api/v1/auth/login", {"email": email, "password": "PleetDemo!2026"}, format="json"
        )
        assert response.status_code == 200, email


def test_seeded_tenant_sees_their_tenancy(settings, api_client):
    settings.DEBUG = True
    call_command("seed_data")
    login = api_client.post(
        "/api/v1/auth/login",
        {"email": "tenant@pleet.test", "password": "PleetDemo!2026"},
        format="json",
    ).json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login['token']}")
    tenancy = api_client.get(f"/api/v1/tenants/{login['user']['id']}/tenancy").json()
    assert tenancy["property"]["agentId"] is not None
    assert len(tenancy["paymentHistory"]) == 2


def test_refuses_without_debug_unless_forced(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_data")
    call_command("seed_data", force=True)
