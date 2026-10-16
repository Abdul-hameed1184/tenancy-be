from django.conf import settings
from django.db import models


class AgentProfile(models.Model):
    """
    Agent-specific data, 1:1 with User.

    A separate table (rather than nullable columns on User) keeps User lean for the three
    roles that never use these fields, and lets verification evolve independently.
    PostgreSQL cannot CHECK across tables that user.role == 'agent'; the accounts service is
    the only code path that creates profiles and enforces it.
    """

    class VerificationStatus(models.TextChoices):
        UNVERIFIED = "unverified", "Unverified"
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="agent_profile",
    )
    agency = models.CharField(max_length=150, blank=True)
    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    trust_score = models.PositiveSmallIntegerField(default=0)
    passport_doc_url = models.URLField(max_length=500, blank=True)
    third_party_check_ref = models.CharField(max_length=100, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(trust_score__gte=0, trust_score__lte=100),
                name="agents_profile_trust_score_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    verification_status__in=["unverified", "pending", "verified", "rejected"]
                ),
                name="agents_profile_verification_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["verification_status"], name="agents_profile_status_idx"),
        ]

    def __str__(self) -> str:
        return f"AgentProfile({self.user_id}, {self.verification_status})"


VERIFICATION_STATUS_CHOICES = AgentProfile.VerificationStatus.choices
