from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.SessionJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Access token from /auth/login or /auth/register. Bound to a "
            "server-side session: logout and password reset revoke it immediately.",
        }
