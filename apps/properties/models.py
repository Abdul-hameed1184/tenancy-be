from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models.functions import Upper
from django.utils import timezone

from apps.common.models import UUIDModel


class Property(UUIDModel):
    class Status(models.TextChoices):
        LISTED = "listed", "Listed"
        OCCUPIED = "occupied", "Occupied"
        UNAVAILABLE = "unavailable", "Unavailable"

    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # never silently delete a portfolio with its landlord
        related_name="properties",
    )
    title = models.CharField(max_length=200)
    address = models.CharField(max_length=300)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    neighborhood = models.CharField(max_length=100)
    photos = ArrayField(models.URLField(max_length=500), default=list, blank=True, size=20)
    videos = ArrayField(models.URLField(max_length=500), default=list, blank=True, size=10)
    bedrooms = models.PositiveSmallIntegerField()
    bathrooms = models.PositiveSmallIntegerField()
    sqft = models.PositiveIntegerField(null=True, blank=True, default=None)
    price_annual = models.PositiveBigIntegerField()  # whole Naira
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.LISTED)
    occupancy_rate = models.PositiveSmallIntegerField(default=0)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "properties"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(occupancy_rate__lte=100),
                name="properties_occupancy_rate_range",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["listed", "occupied", "unavailable"]),
                name="properties_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(price_annual__gt=0), name="properties_price_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["landlord", "-created_at"], name="properties_landlord_idx"),
            models.Index(fields=["status"], name="properties_status_idx"),
            # ?city= uses iexact, which Django compiles to UPPER(city) = UPPER(%s). The index
            # must be on that exact expression or the planner can't use it.
            models.Index(Upper("city"), name="properties_city_ci_idx"),
            models.Index(
                fields=["-created_at"],
                condition=models.Q(featured=True),
                name="properties_featured_idx",
            ),
            # ?search= uses icontains, i.e. UPPER(col) LIKE UPPER('%term%'). A leading
            # wildcard defeats B-trees; trigram GIN indexes on the same UPPER() expression
            # serve it.
            GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="properties_title_trgm"),
            GinIndex(
                OpClass(Upper("neighborhood"), name="gin_trgm_ops"),
                name="properties_hood_trgm",
            ),
            GinIndex(OpClass(Upper("city"), name="gin_trgm_ops"), name="properties_city_trgm"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.city})"


class PropertyAgentAssignment(UUIDModel):
    """
    History of which agent manages a property. Rows are never deleted: unassigning sets
    active=False, so "who managed this in March?" stays answerable.
    """

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="agent_assignments"
    )
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="agent_assignments"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    unassigned_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            # The core invariant, enforced by PostgreSQL: any number of historical rows,
            # at most one active row per property.
            models.UniqueConstraint(
                fields=["property"],
                condition=models.Q(active=True),
                name="properties_one_active_agent",
                violation_error_message="This property already has an active agent.",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(active=True, unassigned_at__isnull=True)
                    | models.Q(active=False, unassigned_at__isnull=False)
                ),
                name="properties_assignment_active_xor_unassigned",
            ),
        ]
        indexes = [
            # "properties this agent actively manages", the hottest lookup for agents.
            models.Index(
                fields=["agent", "property"],
                condition=models.Q(active=True),
                name="properties_active_by_agent_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.agent_id} -> {self.property_id} ({'active' if self.active else 'ended'})"


class PropertyTenantRequest(UUIDModel):
    class Action(models.TextChoices):
        ASSIGN = "assign", "Assign tenant"
        REMOVE = "remove", "Remove tenant"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="tenant_requests"
    )
    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="property_tenant_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tenant_requests_created"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tenant_requests_decided",
    )
    action = models.CharField(max_length=8, choices=Action.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    unit = models.CharField(max_length=50, blank=True)
    lease_start = models.DateField(null=True, blank=True)
    next_due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "tenant", "action"],
                condition=models.Q(status="pending"),
                name="properties_one_pending_tenant_req",
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=["assign", "remove"]),
                name="properties_tenant_req_action_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "approved", "rejected"]),
                name="properties_tenant_req_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["property", "-created_at"], name="prop_tenant_req_recent_idx"
            ),
        ]


PROPERTY_STATUS_CHOICES = Property.Status.choices  # referenced by OpenAPI enum naming
