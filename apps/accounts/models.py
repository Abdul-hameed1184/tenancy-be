from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.common.models import UUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    @staticmethod
    def normalize_email(email: str) -> str:
        # Lower-case the whole address (not just the domain, as Django does) so lookups,
        # the case-insensitive unique index and what we store all agree.
        return (email or "").strip().lower()

    def get_by_natural_key(self, email: str):
        return self.get(email=self.normalize_email(email))

    def create_user(self, email: str, password: str | None = None, **fields):
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email), **fields)
        user.set_password(password)  # None -> unusable password
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **fields):
        fields.setdefault("role", User.Role.ADMIN)
        fields.setdefault("is_staff", True)
        fields.setdefault("is_superuser", True)
        if fields["role"] != User.Role.ADMIN:
            raise ValueError("Superusers must have the admin role.")
        # Created from the command line by an operator: nothing to prove by email.
        fields.setdefault("email_verified_at", timezone.now())
        return self.create_user(email, password, **fields)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        LANDLORD = "landlord", "Landlord"
        AGENT = "agent", "Agent"
        TENANT = "tenant", "Tenant"

    # Unique index + a CHECK that the value is lower-case: together they make uniqueness
    # case-insensitive at the database level with a single index.
    email = models.EmailField(
        max_length=254,
        unique=True,
        error_messages={"unique": "A user with this email already exists."},
    )
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=16, choices=Role.choices)
    avatar_url = models.URLField(max_length=500, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    # is_staff only gates the Django admin site; API authorization uses `role`.
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    # Set when the user follows the emailed verification link. Until then they can sign in
    # but every dashboard API answers 403 "email_not_verified".
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email=Lower("email")),
                name="accounts_user_email_lowercase",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["admin", "landlord", "agent", "tenant"]),
                name="accounts_user_role_valid",
            ),
        ]
        indexes = [models.Index(fields=["role"], name="accounts_user_role_idx")]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}> ({self.role})"

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_landlord(self) -> bool:
        return self.role == self.Role.LANDLORD

    @property
    def is_agent(self) -> bool:
        return self.role == self.Role.AGENT

    @property
    def is_tenant(self) -> bool:
        return self.role == self.Role.TENANT


class AuthSessionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(revoked_at__isnull=True, expires_at__gt=timezone.now())


class AuthSession(UUIDModel):
    """
    One row per login. Access tokens carry its id as `sid`; refresh tokens carry `sid` plus
    a `jti`, and only the jti stored in `current_jti` is accepted. Refreshing swaps in a new
    jti, so every refresh token is single-use; presenting a stale one is treated as theft
    and revokes the session.

    Expiry is absolute (fixed at login), so rotation cannot keep a stolen session alive
    forever.
    """

    class RevokeReason(models.TextChoices):
        LOGOUT = "logout", "Logout"
        REUSE_DETECTED = "reuse_detected", "Refresh token reuse detected"
        PASSWORD_RESET = "password_reset", "Password reset"
        ADMIN = "admin", "Revoked by admin"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="auth_sessions")
    current_jti = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=32, choices=RevokeReason.choices, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=256, blank=True)

    objects = AuthSessionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(revoked_at__isnull=True) | ~models.Q(revoke_reason=""),
                name="accounts_authsession_revoked_has_reason",
            ),
        ]
        indexes = [
            # "this user's live sessions" (revoke-all on password reset) and cleanup jobs.
            models.Index(
                fields=["user"],
                condition=models.Q(revoked_at__isnull=True),
                name="accounts_authsession_live_idx",
            ),
            models.Index(fields=["expires_at"], name="accounts_authsession_exp_idx"),
        ]

    def __str__(self) -> str:
        return f"AuthSession({self.user_id}, revoked={self.revoked_at is not None})"
