from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from .models import AuthSession


class SessionJWTAuthentication(JWTAuthentication):
    """
    Bearer JWT authentication that also requires the token's session to be live.

    Plain stateless JWTs stay valid until they expire, so logout and password reset could
    not take effect for up to the access lifetime. Checking the session costs nothing extra:
    simplejwt would run one query to load the user anyway, and this replaces it with one
    query that joins session -> user -> agent profile.
    """

    def get_user(self, validated_token):
        session_id = validated_token.get("sid")
        user_id = validated_token.get("user_id")
        if not session_id or not user_id:
            raise InvalidToken("Token is missing session claims.")

        session = (
            AuthSession.objects.active()
            .select_related("user", "user__agent_profile")
            .filter(id=session_id, user_id=user_id, user__is_active=True)
            .first()
        )
        if session is None:
            raise AuthenticationFailed(
                "Your session has expired. Please log in again.", code="session_inactive"
            )
        user = session.user
        user.auth_session_id = session.id
        return user
