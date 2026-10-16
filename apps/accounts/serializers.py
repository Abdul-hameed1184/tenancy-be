from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.agents.models import AgentProfile

from .models import User
from .services import SELF_REGISTERABLE_ROLES


class OmitEmptyMixin:
    """Drop optional fields whose value is empty, matching `field?: type` in the contract."""

    omit_if_empty: tuple[str, ...] = ()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field in self.omit_if_empty:
            if data.get(field) in ("", None):
                data.pop(field, None)
        return data


class UserSerializer(OmitEmptyMixin, serializers.ModelSerializer):
    avatarUrl = serializers.URLField(source="avatar_url", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    # Additive to the contract: lets the frontend route unverified users to "check your inbox".
    emailVerified = serializers.BooleanField(source="is_email_verified", read_only=True)

    omit_if_empty = ("avatarUrl", "phone")

    class Meta:
        model = User
        fields = ["id", "name", "email", "role", "avatarUrl", "phone", "createdAt", "emailVerified"]
        read_only_fields = fields


class AgentProfileSerializer(UserSerializer):
    """
    `AgentProfile extends User` in the contract: one flat object built from User plus its
    agent_profile row. This full variant is for the agent themself and admins; public agent
    listings (Milestone 9) use a variant without the private document fields.
    """

    agency = serializers.CharField(source="agent_profile.agency", read_only=True)
    verificationStatus = serializers.CharField(
        source="agent_profile.verification_status", read_only=True
    )
    trustScore = serializers.IntegerField(source="agent_profile.trust_score", read_only=True)
    passportDocUrl = serializers.CharField(source="agent_profile.passport_doc_url", read_only=True)
    thirdPartyCheckRef = serializers.CharField(
        source="agent_profile.third_party_check_ref", read_only=True
    )
    # Derived from active property assignments; list endpoints annotate it in SQL.
    assetsManagedCount = serializers.SerializerMethodField()

    omit_if_empty = (*UserSerializer.omit_if_empty, "passportDocUrl", "thirdPartyCheckRef")

    class Meta(UserSerializer.Meta):
        fields = [
            *UserSerializer.Meta.fields,
            "agency",
            "verificationStatus",
            "trustScore",
            "passportDocUrl",
            "thirdPartyCheckRef",
            "assetsManagedCount",
        ]
        read_only_fields = fields

    def get_assetsManagedCount(self, user) -> int:
        return getattr(user, "assets_managed_count", 0)


def serialize_user(user: User) -> dict:
    """User, or AgentProfile for agents, as /auth/me and the auth responses return."""
    if user.is_agent:
        try:
            user.agent_profile  # noqa: B018 (raises if the row is missing)
        except AgentProfile.DoesNotExist:
            return UserSerializer(user).data
        if not hasattr(user, "assets_managed_count"):
            from apps.agents.selectors import assets_managed_count

            user.assets_managed_count = assets_managed_count(user)
        return AgentProfileSerializer(user).data
    return UserSerializer(user).data


# --- Inputs -------------------------------------------------------------------------------


ROLE_CHOICES = User.Role.choices
SELF_REGISTER_ROLE_CHOICES = [(r.value, r.label) for r in User.Role if r in SELF_REGISTERABLE_ROLES]


class RegisterSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=SELF_REGISTER_ROLE_CHOICES)
    name = serializers.CharField(max_length=150, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_email(self, value: str) -> str:
        email = User.objects.normalize_email(value)
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate(self, attrs):
        # Validate against a transient user so the similarity check sees name and email.
        candidate = User(email=attrs["email"], name=attrs["name"], role=attrs["role"])
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs


class LoginSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ROLE_CHOICES, required=False)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class ResetPasswordSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)


class ProfileUpdateSerializer(serializers.Serializer):
    # `id` is sent by the frontend but the URL identifies the user; it is accepted and ignored.
    id = serializers.CharField(required=False)
    name = serializers.CharField(max_length=150, required=False, trim_whitespace=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    # Additive: a Cloudinary URL from POST /uploads/signature (purpose "avatar"), or "" to clear.
    avatarUrl = serializers.CharField(
        source="avatar_url", max_length=500, required=False, allow_blank=True
    )

    def validate_avatarUrl(self, value: str) -> str:
        if not value:
            return value
        from apps.uploads.cloudinary import InvalidUpload, assert_owned_upload

        try:
            assert_owned_upload(value, user=self.context["user"], purpose="avatar")
        except InvalidUpload as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return value


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)


class ResendVerificationSerializer(serializers.Serializer):
    """Body for anonymous callers; a signed-in caller's own account is used instead."""

    email = serializers.EmailField(max_length=254, required=False)


class AuthResponseSerializer(serializers.Serializer):
    """Schema-only: the shape of register/login responses."""

    user = UserSerializer()
    token = serializers.CharField()


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField()


class WebSocketTicketSerializer(serializers.Serializer):
    """Schema-only: the realtime ticket response."""

    ticket = serializers.CharField()
    expiresIn = serializers.IntegerField()
