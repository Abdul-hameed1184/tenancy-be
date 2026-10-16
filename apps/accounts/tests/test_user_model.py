import uuid

import pytest
from django.conf import settings
from django.db import IntegrityError, connection

from apps.accounts.models import User
from apps.common.uuids import uuid7

pytestmark = pytest.mark.django_db


def make_user(**overrides) -> User:
    fields = {"email": "ada@example.com", "name": "Ada", "role": User.Role.TENANT}
    fields.update(overrides)
    return User.objects.create_user(password="s3cure-pass!", **fields)


def test_create_user_normalizes_email_and_hashes_password():
    user = make_user(email="  Ada.Lovelace@Example.COM ")
    assert user.email == "ada.lovelace@example.com"
    assert user.password != "s3cure-pass!"
    assert user.check_password("s3cure-pass!")


def test_primary_key_is_uuid7():
    user = make_user()
    assert isinstance(user.id, uuid.UUID)
    assert user.id.version == 7


def test_lookup_by_email_is_case_insensitive():
    user = make_user()
    assert User.objects.get_by_natural_key("ADA@example.com") == user


def test_duplicate_email_differing_only_in_case_is_rejected():
    make_user(email="ada@example.com")
    with pytest.raises(IntegrityError):
        make_user(email="ADA@EXAMPLE.COM")


def test_database_rejects_uppercase_email_written_without_the_model():
    """The CHECK constraint protects writes that bypass save(), e.g. raw SQL or bulk tools."""
    sql = (
        "INSERT INTO accounts_user (id, password, is_superuser, email, name, role, "
        "avatar_url, phone, is_active, is_staff, created_at) "
        "VALUES (%s, %s, false, %s, %s, %s, %s, %s, true, false, now())"
    )
    params = [uuid7(), "", "Mixed@Case.com", "x", "tenant", "", ""]
    with pytest.raises(IntegrityError), connection.cursor() as cursor:
        cursor.execute(sql, params)


def test_database_rejects_unknown_role():
    with pytest.raises(IntegrityError):
        User.objects.bulk_create([User(email="x@example.com", name="X", role="superhero")])


def test_create_superuser_gets_admin_role_and_staff_access():
    admin = User.objects.create_superuser("root@example.com", "pw-123456!", name="Root")
    assert admin.role == User.Role.ADMIN
    assert admin.is_admin and admin.is_staff and admin.is_superuser


def test_create_superuser_with_non_admin_role_is_refused():
    with pytest.raises(ValueError):
        User.objects.create_superuser("x@example.com", "pw", name="X", role="tenant")


def test_role_helpers():
    assert make_user(role="landlord").is_landlord
    assert make_user(email="b@example.com", role="agent").is_agent


def test_production_hasher_is_argon2():
    from config.settings import base

    assert base.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")
    assert settings.AUTH_USER_MODEL == "accounts.User"
