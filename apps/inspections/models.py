from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel


class Inspection(UUIDModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    property = models.ForeignKey(
        "properties.Property", on_delete=models.PROTECT, related_name="inspections"
    )
    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_inspections"
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inspections"
    )
    prospect_name = models.CharField(max_length=150)
    requested_at = models.DateTimeField(default=timezone.now, editable=False)
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["scheduled_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["requested", "confirmed", "completed", "cancelled"]),
                name="inspections_status_valid",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="cancelled") | models.Q(cancelled_at__isnull=False),
                name="inspections_cancelled_has_timestamp",
            ),
        ]
        indexes = [
            # Agent dashboards: "my upcoming inspections", ordered by time.
            models.Index(fields=["agent", "status", "scheduled_at"], name="insp_agent_status_idx"),
            models.Index(fields=["tenant", "scheduled_at"], name="insp_tenant_idx"),
            models.Index(fields=["property", "scheduled_at"], name="insp_property_idx"),
        ]

    def __str__(self) -> str:
        return f"Inspection({self.property_id} @ {self.scheduled_at:%Y-%m-%d %H:%M}, {self.status})"


# Legal source states for each transition endpoint.
TRANSITIONS = {
    "confirm": ([Inspection.Status.REQUESTED], Inspection.Status.CONFIRMED),
    "complete": ([Inspection.Status.CONFIRMED], Inspection.Status.COMPLETED),
    "cancel": (
        [Inspection.Status.REQUESTED, Inspection.Status.CONFIRMED],
        Inspection.Status.CANCELLED,
    ),
}

INSPECTION_STATUS_CHOICES = Inspection.Status.choices
