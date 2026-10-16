from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsVerified, ensure_self

from . import realtime, services
from .models import User
from .serializers import (
    AuthResponseSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    ResetPasswordSerializer,
    TokenResponseSerializer,
    UserSerializer,
    VerifyEmailSerializer,
    WebSocketTicketSerializer,
    serialize_user,
)
from .throttles import (
    EmailVerificationThrottle,
    LoginThrottle,
    PasswordResetThrottle,
    RegisterThrottle,
    TokenRefreshThrottle,
)
from .verification import InvalidVerificationToken

AUTH_TAG = ["auth"]


def _session_response(user: User, issued: services.SessionTokens, status_code=200) -> Response:
    response = Response({"user": serialize_user(user), "token": issued.access}, status=status_code)
    _set_refresh_cookie(response, issued.refresh)
    return response


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    cookie = settings.AUTH_REFRESH_COOKIE
    response.set_cookie(
        cookie["key"],
        refresh,
        max_age=int(settings.JWT_REFRESH_TOKEN_LIFETIME.total_seconds()),
        path=cookie["path"],
        httponly=cookie["httponly"],
        secure=cookie["secure"],
        samesite=cookie["samesite"],
    )


def _clear_refresh_cookie(response: Response) -> None:
    cookie = settings.AUTH_REFRESH_COOKIE
    response.delete_cookie(cookie["key"], path=cookie["path"], samesite=cookie["samesite"])


class PublicAuthView(APIView):
    # No authentication at all: a stale/invalid Authorization header on a login request
    # must not turn into a 401 before the credentials are even checked.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        # With no authenticators DRF has no WWW-Authenticate value and silently downgrades
        # AuthenticationFailed to 403. Bad credentials must stay a 401.
        return 'Bearer realm="api"'


class RegisterView(PublicAuthView):
    throttle_classes = [RegisterThrottle]

    @extend_schema(
        tags=AUTH_TAG, request=RegisterSerializer, responses={201: AuthResponseSerializer}
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.register_user(**serializer.validated_data, request=request)
        except services.DuplicateEmail as exc:
            raise ValidationError({"email": ["A user with this email already exists."]}) from exc

        issued = services.start_session(user, request)
        return _session_response(user, issued, status_code=status.HTTP_201_CREATED)


class LoginView(PublicAuthView):
    throttle_classes = [LoginThrottle]

    @extend_schema(
        tags=AUTH_TAG,
        request=LoginSerializer,
        responses={
            200: AuthResponseSerializer,
            401: OpenApiResponse(description="Bad credentials"),
            403: OpenApiResponse(description="Email not verified"),
        },
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.login(**serializer.validated_data, request=request)
        except services.VerificationError as exc:
            raise PermissionDenied(str(exc)) from exc
        except services.AuthError as exc:
            raise AuthenticationFailed(str(exc)) from exc
        issued = services.start_session(user, request)
        return _session_response(user, issued)


class RefreshView(PublicAuthView):
    """
    Additive to the contract. Reads the HttpOnly refresh cookie and returns a new access
    token while rotating the cookie.

    CSRF: the cookie is sent automatically by browsers, so a cross-site form could try to
    trigger this. Requiring a custom header defeats that: browsers only attach custom
    headers to cross-origin requests after a CORS preflight, which our allowlist refuses
    for foreign origins. SameSite=Lax on the cookie is a second layer.
    """

    throttle_classes = [TokenRefreshThrottle]

    @extend_schema(tags=AUTH_TAG, request=None, responses={200: TokenResponseSerializer})
    def post(self, request):
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            raise PermissionDenied("Missing X-Requested-With header.")
        raw = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE["key"])
        if not raw:
            raise AuthenticationFailed("Your session has expired. Please log in again.")
        try:
            issued = services.rotate_session(raw, request)
        except services.AuthError as exc:
            response = Response({"message": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
            _clear_refresh_cookie(response)
            return response
        response = Response({"token": issued.access})
        _set_refresh_cookie(response, issued.refresh)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=AUTH_TAG, responses={200: UserSerializer})
    def get(self, request):
        return Response(serialize_user(request.user))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=AUTH_TAG, request=None, responses={204: None})
    def post(self, request):
        services.logout(request.user, request.user.auth_session_id, request)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_refresh_cookie(response)
        return response


class ForgotPasswordView(PublicAuthView):
    throttle_classes = [PasswordResetThrottle]

    @extend_schema(tags=AUTH_TAG, request=ForgotPasswordSerializer, responses={204: None})
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(serializer.validated_data["email"], request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResetPasswordView(PublicAuthView):
    throttle_classes = [PasswordResetThrottle]

    @extend_schema(tags=AUTH_TAG, request=ResetPasswordSerializer, responses={204: None})
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.reset_password(
                serializer.validated_data["token"], serializer.validated_data["password"], request
            )
        except services.InvalidResetToken as exc:
            raise ValidationError(
                {"token": ["This reset link is invalid or has expired."]}
            ) from exc
        except DjangoValidationError as exc:
            raise ValidationError({"password": list(exc.messages)}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyEmailView(PublicAuthView):
    """Additive: consume the emailed link. Returns the (now verified) user."""

    throttle_classes = [EmailVerificationThrottle]

    @extend_schema(tags=AUTH_TAG, request=VerifyEmailSerializer, responses={200: UserSerializer})
    def post(self, request):
        body = VerifyEmailSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            user = services.verify_email(body.validated_data["token"], request)
        except InvalidVerificationToken as exc:
            raise ValidationError(
                {"token": ["This verification link is invalid or has expired."]}
            ) from exc
        return Response(serialize_user(user))


class ResendVerificationView(APIView):
    """
    Additive: re-send the verification email. Signed-in callers get it for their own
    account (the body is ignored); anonymous callers name an email. Always 204, so the
    endpoint reveals nothing about which addresses are registered.
    """

    permission_classes = [AllowAny]
    throttle_classes = [EmailVerificationThrottle]

    @extend_schema(tags=AUTH_TAG, request=ResendVerificationSerializer, responses={204: None})
    def post(self, request):
        user = request.user if request.user.is_authenticated else None
        if user is None:
            body = ResendVerificationSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            email = body.validated_data.get("email")
            user = User.objects.filter(email=User.objects.normalize_email(email or "")).first()
        services.resend_verification(user, request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserDetailView(APIView):
    permission_classes = [IsVerified]

    @extend_schema(tags=["users"], request=ProfileUpdateSerializer, responses={200: UserSerializer})
    def patch(self, request, pk):
        # Ownership comes from the token, never from the URL or body.
        ensure_self(request.user, pk, what="profile")
        serializer = ProfileUpdateSerializer(
            data=request.data, partial=True, context={"user": request.user}
        )
        serializer.is_valid(raise_exception=True)
        user = services.update_profile(request.user, serializer.validated_data, request)
        return Response(serialize_user(user))


class WebSocketTicketView(APIView):
    """Additive: exchange a Bearer token for a 30-second, single-use WebSocket ticket."""

    permission_classes = [IsVerified]

    @extend_schema(
        tags=["realtime"],
        request=None,
        responses={200: WebSocketTicketSerializer},
        description=(
            "Connect within expiresIn seconds: ws(s)://<host>/ws/threads/<threadId>/?ticket=... "
            "or /ws/notifications/?ticket=... . A ticket works once."
        ),
    )
    def post(self, request):
        ticket = realtime.issue_ticket(request.user)
        return Response({"ticket": ticket, "expiresIn": settings.WS_TICKET_TTL_SECONDS})
