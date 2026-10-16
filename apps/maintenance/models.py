from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel


class MaintenanceRequest(UUIDModel):
    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class Status(models.TextChoices):
        REPORTED = "reported", "Reported"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    property = models.ForeignKey(
        "properties.Property", on_delete=models.PROTECT, related_name="maintenance_requests"
    )
    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="maintenance_requests"
    )
    issue_type = models.CharField(max_length=100)
    description = models.TextField(max_length=5000)
    priority = models.CharField(max_length=8, choices=Priority.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REPORTED)
    reported_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-reported_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(priority__in=["high", "medium", "low"]),
                name="maintenance_priority_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["reported", "in_progress", "completed"]),
                name="maintenance_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status="completed", completed_at__isnull=False)
                | (~models.Q(status="completed") & models.Q(completed_at__isnull=True)),
                name="maintenance_completed_at_iff_completed",
            ),
        ]
        indexes = [
            models.Index(fields=["property", "status"], name="maint_property_status_idx"),
            models.Index(fields=["tenant", "-reported_at"], name="maint_tenant_recent_idx"),
            # Dashboards count what's still open per property.
            models.Index(
                fields=["property", "priority"],
                condition=~models.Q(status="completed"),
                name="maint_open_by_property_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.issue_type} ({self.status}) @ {self.property_id}"


# Forward-only workflow (matches the agent UI): each target status has one legal predecessor.
PREDECESSOR = {
    MaintenanceRequest.Status.IN_PROGRESS: MaintenanceRequest.Status.REPORTED,
    MaintenanceRequest.Status.COMPLETED: MaintenanceRequest.Status.IN_PROGRESS,
}

MAINTENANCE_STATUS_CHOICES = MaintenanceRequest.Status.choices
