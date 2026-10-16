import hashlib

import pytest

from apps.uploads import cloudinary
from tests.factories import LandlordFactory, UserFactory

API = "/api/v1"
CLOUD = {
    "CLOUDINARY_CLOUD_NAME": "pleet-test",
    "CLOUDINARY_API_KEY": "123456789012345",
    "CLOUDINARY_API_SECRET": "test-secret",
    "CLOUDINARY_ROOT_FOLDER": "pleet",
    "CLOUDINARY_SIGNATURE_ALGORITHM": "sha1",
}


@pytest.fixture
def configured(settings):
    for key, value in CLOUD.items():
        setattr(settings, key, value)
    return settings


def delivery_url(user, purpose="property_photo", ext="jpg", cloud="pleet-test"):
    folder = cloudinary.folder_for(user, purpose)
    resource_type = cloudinary.PURPOSES[purpose].resource_type
    return f"https://res.cloudinary.com/{cloud}/{resource_type}/upload/v1759360000/{folder}/abc123.{ext}"


# --- Signing --------------------------------------------------------------------------------


def test_signature_matches_cloudinarys_algorithm():
    """sorted k=v pairs joined by &, secret appended, SHA-1 (Cloudinary's documented scheme)."""
    params = {"timestamp": 1315060510, "public_id": "sample_image", "eager": "w_400,h_300,c_pad"}
    expected = hashlib.sha1(  # noqa: S324 (Cloudinary protocol default; sha256 also supported)
        b"eager=w_400,h_300,c_pad&public_id=sample_image&timestamp=1315060510abcd"
    ).hexdigest()
    assert cloudinary.sign(params, "abcd") == expected
    assert (
        cloudinary.sign(params, "abcd", "sha256")
        == hashlib.sha256(
            b"eager=w_400,h_300,c_pad&public_id=sample_image&timestamp=1315060510abcd"
        ).hexdigest()
    )


@pytest.mark.django_db
def test_signed_upload_contents(configured):
    landlord = LandlordFactory()
    result = cloudinary.signed_upload(landlord, "property_photo", now=1759360000)
    fields = result["fields"]

    assert result["uploadUrl"] == "https://api.cloudinary.com/v1_1/pleet-test/image/upload"
    assert fields["folder"] == f"pleet/properties/{landlord.pk}"
    assert fields["allowed_formats"] == "jpg,jpeg,png,webp"
    assert fields["transformation"] == "c_limit,w_2400,h_2400"
    assert fields["api_key"] == "123456789012345"
    assert len(fields["public_id"]) == 32  # server-chosen random id
    assert result["expiresAt"] == 1759360000 + 3600
    # The secret is used, never sent.
    assert "test-secret" not in str(result)
    signed = {k: v for k, v in fields.items() if k not in {"api_key", "signature"}}
    assert fields["signature"] == cloudinary.sign(signed, "test-secret")


@pytest.mark.django_db
def test_every_signature_gets_a_fresh_public_id(configured):
    landlord = LandlordFactory()
    first = cloudinary.signed_upload(landlord, "property_photo")["fields"]["public_id"]
    second = cloudinary.signed_upload(landlord, "property_photo")["fields"]["public_id"]
    assert first != second


@pytest.mark.django_db
def test_signed_property_video_upload_uses_video_resource(configured):
    landlord = LandlordFactory()
    result = cloudinary.signed_upload(landlord, "property_video", now=1759360000)

    assert result["uploadUrl"] == "https://api.cloudinary.com/v1_1/pleet-test/video/upload"
    assert result["fields"]["allowed_formats"] == "mp4,mov,webm"
    assert "transformation" not in result["fields"]
    assert result["maxBytes"] == 100 * 1024 * 1024


# --- Endpoint -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_landlord_gets_property_photo_signature(api_client, authenticate, configured):
    authenticate(api_client, LandlordFactory())
    response = api_client.post(
        f"{API}/uploads/signature", {"purpose": "property_photo"}, format="json"
    )
    assert response.status_code == 200
    assert set(response.json()) == {"uploadUrl", "fields", "maxBytes", "allowedFormats",
                                    "expiresAt"}  # fmt: skip


@pytest.mark.django_db
def test_landlord_gets_property_video_signature(api_client, authenticate, configured):
    authenticate(api_client, LandlordFactory())
    response = api_client.post(
        f"{API}/uploads/signature", {"purpose": "property_video"}, format="json"
    )
    assert response.status_code == 200
    assert "/video/upload" in response.json()["uploadUrl"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["tenant", "agent", "admin"])
def test_only_landlords_upload_property_photos(api_client, authenticate, configured, role):
    authenticate(api_client, UserFactory(role=role))
    response = api_client.post(
        f"{API}/uploads/signature", {"purpose": "property_photo"}, format="json"
    )
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["tenant", "agent", "landlord", "admin"])
def test_everyone_can_upload_an_avatar(api_client, authenticate, configured, role):
    authenticate(api_client, UserFactory(role=role))
    response = api_client.post(f"{API}/uploads/signature", {"purpose": "avatar"}, format="json")
    assert response.status_code == 200


@pytest.mark.django_db
def test_unknown_purpose_and_anonymous(api_client, authenticate, configured):
    assert api_client.post(f"{API}/uploads/signature", {"purpose": "avatar"}).status_code == 401
    authenticate(api_client, LandlordFactory())
    response = api_client.post(f"{API}/uploads/signature", {"purpose": "malware"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_unconfigured_server_answers_503(api_client, authenticate, settings):
    settings.CLOUDINARY_API_SECRET = ""
    authenticate(api_client, LandlordFactory())
    response = api_client.post(f"{API}/uploads/signature", {"purpose": "avatar"}, format="json")
    assert response.status_code == 503
    assert response.json() == {"message": "Image uploads aren't configured on this server."}


# --- Using uploaded URLs --------------------------------------------------------------------


def property_body(photos):
    return {"title": "Flat", "address": "1 Road", "city": "Lagos", "state": "Lagos",
            "neighborhood": "Yaba", "bedrooms": 1, "bathrooms": 1, "sqft": 500,
            "priceAnnual": 1_000_000, "photos": photos}  # fmt: skip


@pytest.mark.django_db
def test_property_accepts_own_uploads_and_external_urls(api_client, authenticate, configured):
    landlord = LandlordFactory()
    authenticate(api_client, landlord)
    photos = [delivery_url(landlord), "https://images.unsplash.com/photo-1.jpg"]
    response = api_client.post(f"{API}/properties", property_body(photos), format="json")
    assert response.status_code == 201
    assert response.json()["photos"] == photos


@pytest.mark.django_db
def test_property_accepts_own_uploaded_video(api_client, authenticate, configured):
    landlord = LandlordFactory()
    authenticate(api_client, landlord)
    video_url = delivery_url(landlord, purpose="property_video", ext="mp4")

    response = api_client.post(
        f"{API}/properties",
        property_body(["https://images.example.com/1.jpg"]) | {"videos": [video_url]},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["videos"] == [video_url]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "make_url",
    [
        lambda me, other: delivery_url(other),  # someone else's folder
        lambda me, other: delivery_url(me, cloud="someone-elses-cloud"),
        lambda me, other: delivery_url(me, purpose="avatar"),  # wrong purpose folder
        lambda me, other: delivery_url(me, ext="svg"),  # format outside the allow-list
    ],
    ids=["other-landlord", "other-cloud", "avatar-folder", "svg"],
)
def test_property_rejects_foreign_or_invalid_uploads(
    api_client, authenticate, configured, make_url
):
    me, other = LandlordFactory(), LandlordFactory()
    authenticate(api_client, me)
    body = property_body([make_url(me, other)])
    response = api_client.post(f"{API}/properties", body, format="json")
    assert response.status_code == 400
    assert "photos" in response.json()["errors"]


@pytest.mark.django_db
def test_avatar_update_accepts_own_upload_only(api_client, authenticate, configured):
    me, other = UserFactory(), UserFactory()
    authenticate(api_client, me)
    url = delivery_url(me, purpose="avatar", ext="png")

    ok = api_client.patch(f"{API}/users/{me.id}", {"avatarUrl": url}, format="json")
    assert ok.status_code == 200 and ok.json()["avatarUrl"] == url

    foreign = delivery_url(other, purpose="avatar")
    bad = api_client.patch(f"{API}/users/{me.id}", {"avatarUrl": foreign}, format="json")
    assert bad.status_code == 400

    external = api_client.patch(
        f"{API}/users/{me.id}", {"avatarUrl": "https://evil.example/x.png"}, format="json"
    )
    assert external.status_code == 400

    cleared = api_client.patch(f"{API}/users/{me.id}", {"avatarUrl": ""}, format="json")
    assert "avatarUrl" not in cleared.json()
