import re

import pytest
from django.core import mail, signing
from django.utils import timezone

from apps.accounts import verification
from apps.accounts.models import User
from apps.agents.models import AgentProfile
from apps.audit.models import AuditLog
from tests.factories import PropertyFactory, UserFactory

pytestmark = pytest.mark.django_db
API = "/api/v1"
STRONG = "Tr1cky-Passphrase!"


def register(client, email="new@example.com", role="landlord"):
    return client.post(
        f"{API}/auth/register",
        {"role": role, "name": "New Person", "email": email, "password": STRONG},
        format="json",
    )


def link_token(message) -> str:
    return re.search(r"verify-email\?token=(\S+)", message.body).group(1)


@pytest.fixture
def unverified():
    return UserFactory(role="landlord", email_verified_at=None)


# --- Registration sends the link; the account starts unverified -----------------------------


def test_registration_emails_a_verification_link(api_client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = register(api_client)
    assert response.status_code == 201
    assert response.json()["user"]["emailVerified"] is False
    [message] = mail.outbox
    assert message.to == ["new@example.com"]
    assert "http://localhost:5173/auth/verify-email?token=" in message.body
    assert message.content_subtype == "plain"
    assert len(message.alternatives) == 1
    assert message.alternatives[0].mimetype == "text/html"
    assert "Confirm email" in message.alternatives[0].content
    assert "verify-email?token=" in message.alternatives[0].content


def test_unverified_user_can_sign_in_and_read_their_profile(api_client, authenticate, unverified):
    authenticate(api_client, unverified)
    me = api_client.get(f"{API}/auth/me")
    assert me.status_code == 200 and me.json()["emailVerified"] is False


# --- Dashboards are locked until verified ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/tenancies",
        "/maintenance-requests",
        "/inspections",
        "/threads",
        "/notifications",
        "/reports",
    ],
)
def test_dashboard_apis_answer_403_with_code(api_client, authenticate, unverified, path):
    authenticate(api_client, unverified)
    response = api_client.get(f"{API}{path}")
    assert response.status_code == 403
    assert response.json() == {
        "message": "Please verify your email address to continue.",
        "code": "email_not_verified",
    }


def test_writes_and_realtime_are_locked_too(api_client, authenticate, unverified):
    authenticate(api_client, unverified)
    body = {"title": "x", "address": "x", "city": "x", "state": "x", "neighborhood": "x",
            "bedrooms": 1, "bathrooms": 1, "sqft": 1, "priceAnnual": 1, "photos": []}  # fmt: skip
    assert api_client.post(f"{API}/properties", body, format="json").status_code == 403
    assert api_client.post(f"{API}/realtime/ticket").status_code == 403
    assert api_client.post(f"{API}/uploads/signature", {"purpose": "avatar"}).status_code == 403
    response = api_client.patch(f"{API}/users/{unverified.id}", {"name": "x"}, format="json")
    assert response.status_code == 403


def test_public_pages_still_work_while_unverified(api_client, authenticate, unverified):
    PropertyFactory()
    authenticate(api_client, unverified)
    assert api_client.get(f"{API}/properties").status_code == 200
    assert api_client.get(f"{API}/agents").status_code == 200


def test_anonymous_still_gets_401_not_the_verification_403(api_client):
    response = api_client.get(f"{API}/tenancies")
    assert response.status_code == 401
    assert "code" not in response.json()


# --- Verifying ------------------------------------------------------------------------------


def test_following_the_link_verifies_and_unlocks(
    api_client, authenticate, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        token = register(api_client).json()["token"]
    link = link_token(mail.outbox[0])
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert api_client.get(f"{API}/reports").status_code == 403

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(f"{API}/auth/verify-email", {"token": link}, format="json")

    assert response.status_code == 200 and response.json()["emailVerified"] is True
    assert api_client.get(f"{API}/reports").status_code == 200  # same access token now works
    assert AuditLog.objects.filter(action="EMAIL_VERIFIED").count() == 1
    assert mail.outbox[-1].subject == "Welcome to PLEET"


def test_verifying_agent_email_also_temporarily_verifies_agent_profile(
    api_client, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        register(api_client, email="agent@example.com", role="agent")
    token = link_token(mail.outbox[0])

    with django_capture_on_commit_callbacks(execute=True):
        verify_response = api_client.post(
            f"{API}/auth/verify-email", {"token": token}, format="json"
        )

    assert verify_response.status_code == 200
    assert (
        AgentProfile.objects.get(user_id=verify_response.json()["id"]).verification_status
        == AgentProfile.VerificationStatus.VERIFIED
    )


def test_verifying_twice_is_harmless(api_client, unverified, django_capture_on_commit_callbacks):
    token = verification.make_token(unverified)
    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            assert (
                api_client.post(
                    f"{API}/auth/verify-email", {"token": token}, format="json"
                ).status_code
                == 200
            )
    assert AuditLog.objects.filter(action="EMAIL_VERIFIED").count() == 1
    assert len(mail.outbox) == 1  # one welcome email, not two


@pytest.mark.parametrize("token", ["garbage", "a.b.c", ""])
def test_bad_tokens_are_rejected(api_client, token):
    response = api_client.post(f"{API}/auth/verify-email", {"token": token}, format="json")
    assert response.status_code == 400


def test_tampered_token_is_rejected(api_client, unverified):
    token = verification.make_token(unverified)
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    assert (
        api_client.post(f"{API}/auth/verify-email", {"token": tampered}, format="json").status_code
        == 400
    )


def test_expired_token_is_rejected(api_client, unverified, settings):
    token = verification.make_token(unverified)
    settings.EMAIL_VERIFICATION_TIMEOUT = -1
    response = api_client.post(f"{API}/auth/verify-email", {"token": token}, format="json")
    assert response.json()["message"] == "Token: This verification link is invalid or has expired."


def test_link_dies_if_the_email_changes(api_client, unverified):
    token = verification.make_token(unverified)
    User.objects.filter(pk=unverified.pk).update(email="changed@example.com")
    assert (
        api_client.post(f"{API}/auth/verify-email", {"token": token}, format="json").status_code
        == 400
    )


def test_token_carries_no_secret():
    """The payload is only signed, not encrypted: it must not contain anything sensitive."""
    user = UserFactory(email_verified_at=None)
    payload = signing.loads(verification.make_token(user), salt="pleet.accounts.email-verification")
    assert set(payload) == {"uid", "email"}


# --- Resending ------------------------------------------------------------------------------


def test_signed_in_user_can_resend(api_client, authenticate, unverified):
    authenticate(api_client, unverified)
    assert api_client.post(f"{API}/auth/resend-verification").status_code == 204
    assert [m.to for m in mail.outbox] == [[unverified.email]]


def test_anonymous_resend_reveals_nothing(api_client, unverified):
    UserFactory(email="done@example.com")  # already verified
    for email in (unverified.email, "ghost@example.com", "done@example.com"):
        response = api_client.post(
            f"{API}/auth/resend-verification", {"email": email}, format="json"
        )
        assert response.status_code == 204
    assert [m.to for m in mail.outbox] == [[unverified.email]]


def test_resend_is_throttled(api_client, unverified):
    for _ in range(3):
        api_client.post(f"{API}/auth/resend-verification", {"email": unverified.email})
    response = api_client.post(f"{API}/auth/resend-verification", {"email": unverified.email})
    assert response.status_code == 429


def test_superusers_and_seeded_accounts_start_verified(settings):
    admin = User.objects.create_superuser("root@example.com", "pw-123456!", name="Root")
    assert admin.is_email_verified
    assert UserFactory().email_verified_at <= timezone.now()
