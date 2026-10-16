from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import UUIDModel


class Tenancy(UUIDModel):
    """
    A tenant occupying a unit of a property.

    "Current" means ended_at IS NULL. Ending a tenancy keeps the row (payment history hangs
    off it), so uniqueness rules are partial: they only constrain current tenancies.
    """

    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tenancies"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.PROTECT, related_name="tenancies"
    )
    unit = models.CharField(max_length=50)
    lease_start = models.DateField()
    next_due_date = models.DateField()
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["next_due_date", "created_at"]
        verbose_name_plural = "tenancies"
        constraints = [
            # GET /tenants/:id/tenancy returns a single tenancy, so a tenant holds at most one
            # current tenancy.
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(ended_at__isnull=True),
                name="tenancies_one_current_per_tenant",
                violation_error_message="This tenant already has a current tenancy.",
            ),
            # A unit can't be let to two tenants at once.
            models.UniqueConstraint(
                fields=["property", "unit"],
                condition=models.Q(ended_at__isnull=True),
                name="tenancies_one_current_per_unit",
                violation_error_message="This unit already has a current tenant.",
            ),
            models.CheckConstraint(
                condition=models.Q(next_due_date__gte=models.F("lease_start")),
                name="tenancies_due_not_before_lease_start",
                violation_error_message="Next due date can't be before the lease start.",
            ),
        ]
        indexes = [
            models.Index(
                fields=["property"],
                condition=models.Q(ended_at__isnull=True),
                name="tenancies_current_by_prop_idx",
            ),
            # Rent-due reminders scan current tenancies by due date.
            models.Index(
                fields=["next_due_date"],
                condition=models.Q(ended_at__isnull=True),
                name="tenancies_current_due_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Tenancy({self.tenant_id} @ {self.property_id} unit {self.unit})"

    def clean(self):
        # The database can't CHECK across tables, so role validity is enforced here (used by
        # the admin and every service that creates tenancies).
        from apps.accounts.models import User

        if self.tenant_id and self.tenant.role != User.Role.TENANT:
            raise ValidationError({"tenant": "The tenant must be a user with the tenant role."})
