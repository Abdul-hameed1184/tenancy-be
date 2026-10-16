"""
Throttles for unauthenticated auth endpoints (the brute-force surface).

Counters live in Redis, shared by every process. If Redis is unreachable they fall back
to per-process memory (apps.common.throttles.ResilientThrottleCache): a Redis outage
weakens these limits but never disables them.
"""

import hashlib

from rest_framework.throttling import SimpleRateThrottle

from apps.common.throttles import ResilientThrottleCache

_AUTH_THROTTLE_CACHE = ResilientThrottleCache()


class _IPThrottle(SimpleRateThrottle):
    cache = _AUTH_THROTTLE_CACHE

    def get_cache_key(self, request, view):
        return f"pleet:throttle:{self.scope}:{self.get_ident(request)}"


class LoginThrottle(SimpleRateThrottle):
    """Per IP *and* email: stops guessing one account's password from one address without
    letting a single attacker lock every user out of a shared IP (e.g. an office NAT)."""

    scope = "login"
    cache = _AUTH_THROTTLE_CACHE

    def get_cache_key(self, request, view):
        email = str(request.data.get("email", "")).strip().lower()
        digest = hashlib.sha256(email.encode()).hexdigest()[:32]  # no raw emails in keys
        return f"pleet:throttle:{self.scope}:{self.get_ident(request)}:{digest}"


class RegisterThrottle(_IPThrottle):
    scope = "register"


class PasswordResetThrottle(_IPThrottle):
    scope = "password_reset"


class EmailVerificationThrottle(_IPThrottle):
    scope = "email_verification"


class TokenRefreshThrottle(_IPThrottle):
    scope = "token_refresh"
