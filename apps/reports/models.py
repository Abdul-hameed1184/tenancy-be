from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel


class Report(UUIDModel):
    """
    A flagged listing or user.

    The contract's single `targetId` is stored as two real foreign keys plus a CHECK that
    exactly the one matching `type` is set, so a report can never point at nothing or at
    the wrong kind of thing.
    """

    class Type(models.TextChoices):
        LISTING = "listing", "Listing"
        USER = "user", "User"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    type = models.CharField(max_length=8, choices=Type.choices)
    target_property = models.ForeignKey(
        "properties.Property", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    reason = models.TextField(max_length=2000)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="filed_reports"
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        type="listing", target_property__isnull=False, target_user__isnull=True
                    )
                    | models.Q(type="user", target_user__isnull=False, target_property__isnull=True)
                ),
                name="reports_target_matches_type",
            ),
            models.CheckConstraint(
                condition=models.Q(status="open", resolved_at__isnull=True)
                | models.Q(status="resolved", resolved_at__isnull=False),
                name="reports_resolved_at_iff_resolved",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="reports_status_recent_idx"),
            models.Index(fields=["reported_by", "-created_at"], name="reports_reporter_idx"),
        ]

    def __str__(self) -> str:
        return f"Report({self.type}, {self.status})"

    @property
    def target_id(self):
        return self.target_property_id or self.target_user_id


REPORT_STATUS_CHOICES = Report.Status.choices
REPORT_TYPE_CHOICES = Report.Type.choices
