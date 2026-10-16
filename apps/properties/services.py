from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.audit.services import Action, record
from apps.common.cache import invalidate_on_commit
from apps.common.events import publish
from apps.common.exceptions import Conflict

from .events import AgentAssigned, AgentUnassigned
from .models import Property, PropertyAgentAssignment, PropertyTenantRequest

CREATE_FIELDS = {
    "title",
    "address",
    "city",
    "state",
    "neighborhood",
    "photos",
    "videos",
    "bedrooms",
    "bathrooms",
    "sqft",
    "price_annual",
    "featured",
    "status",
}
# Landlords may edit their listing, including occupancy. The owner and the managing agent
# are not editable here: ownership never changes, and agents change only via /agent.
UPDATE_FIELDS = CREATE_FIELDS | {"occupancy_rate"}


class InvalidAgent(Exception):
    pass


def create_property(*, landlord: User, data: dict, request=None) -> Property:
    fields = {k: v for k, v in data.items() if k in CREATE_FIELDS}
    with transaction.atomic():
        # occupancy starts at 0 and status defaults to listed (contract defaults).
        prop = Property.objects.create(landlord=landlord, occupancy_rate=0, **fields)
        invalidate_on_commit("properties")
        record(Action.PROPERTY_CREATED, actor=landlord, entity=prop, request=request)
    return prop


def update_property(*, prop: Property, actor: User, data: dict, request=None) -> Property:
    changes = {k: v for k, v in data.items() if k in UPDATE_FIELDS}
    if not changes:
        return prop
    with transaction.atomic():
        for field, value in changes.items():
            setattr(prop, field, value)
        prop.save(update_fields=[*changes, "updated_at"])
        invalidate_on_commit("properties")
        record(
            Action.PROPERTY_UPDATED,
            actor=actor,
            entity=prop,
            metadata={"fields": sorted(changes)},
            request=request,
        )
    return prop


def assign_agent(*, prop: Property, agent_id, actor: User, request=None):
    """
    Make `agent_id` the property's single active agent.

    Concurrency: we lock the *property* row. Locking the current assignment isn't enough,
    because when a property has no agent there is no assignment row to lock, and two
    concurrent requests would both insert. With the property locked, a second assignment
    waits, then sees the first one's result. The partial unique index is the backstop: if
    any code path ever skips the lock, the database still refuses a second active row.
    """
    agent = User.objects.filter(pk=agent_id, role=User.Role.AGENT, is_active=True).first()
    if agent is None:
        raise InvalidAgent

    try:
        with transaction.atomic():
            locked = Property.objects.select_for_update().get(pk=prop.pk)
            current = PropertyAgentAssignment.objects.filter(property=locked, active=True).first()
            if current and current.agent_id == agent.pk:
                return current  # already assigned: idempotent, no new history or event

            if current:
                _end(current)
            assignment = PropertyAgentAssignment.objects.create(
                property=locked, agent=agent, assigned_by=actor
            )
            # agentId on properties and assetsManagedCount on agents both change.
            invalidate_on_commit("properties", "agents")
            publish(
                AgentAssigned(
                    property_id=str(locked.pk),
                    landlord_id=str(locked.landlord_id),
                    agent_id=str(agent.pk),
                    previous_agent_id=str(current.agent_id) if current else None,
                    assignment_id=str(assignment.pk),
                )
            )
            record(
                Action.AGENT_ASSIGNED,
                actor=actor,
                entity=locked,
                metadata={
                    "agent_id": str(agent.pk),
                    "previous_agent_id": str(current.agent_id) if current else None,
                },
                request=request,
            )
    except IntegrityError as exc:
        raise Conflict("This property's agent was changed concurrently. Please retry.") from exc
    return assignment


def unassign_agent(*, prop: Property, actor: User, request=None) -> None:
    """Idempotent: removing an agent from a property without one is a no-op."""
    with transaction.atomic():
        locked = Property.objects.select_for_update().get(pk=prop.pk)
        current = PropertyAgentAssignment.objects.filter(property=locked, active=True).first()
        if current is None:
            return
        _end(current)
        invalidate_on_commit("properties", "agents")
        publish(
            AgentUnassigned(
                property_id=str(locked.pk),
                landlord_id=str(locked.landlord_id),
                agent_id=str(current.agent_id),
                assignment_id=str(current.pk),
            )
        )
        record(
            Action.AGENT_UNASSIGNED,
            actor=actor,
            entity=locked,
            metadata={"agent_id": str(current.agent_id)},
            request=request,
        )


def _end(assignment: PropertyAgentAssignment) -> None:
    assignment.active = False
    assignment.unassigned_at = timezone.now()
    assignment.save(update_fields=["active", "unassigned_at"])


def tenant_candidates(*, prop: Property, agent: User, search: str):
    from apps.tenancies.models import Tenancy

    require_property_agent(prop=prop, agent=agent)
    query = search.strip()
    if len(query) < 2:
        return User.objects.none()
    pending_tenant_ids = PropertyTenantRequest.objects.filter(
        action=PropertyTenantRequest.Action.ASSIGN,
        status=PropertyTenantRequest.Status.PENDING,
    ).values("tenant_id")
    return (
        User.objects.filter(role=User.Role.TENANT, is_active=True, name__icontains=query)
        .exclude(pk__in=Tenancy.objects.filter(ended_at__isnull=True).values("tenant_id"))
        .exclude(pk__in=pending_tenant_ids)
        .order_by("name")[:10]
    )


def request_tenant_change(*, prop: Property, actor: User, data: dict, request=None):
    from apps.tenancies.models import Tenancy

    require_property_agent(prop=prop, agent=actor)
    tenant = User.objects.filter(
        pk=data["tenantId"], role=User.Role.TENANT, is_active=True
    ).first()
    if tenant is None:
        raise InvalidTenant("Choose an active tenant account.")

    action = data["action"]
    try:
        with transaction.atomic():
            locked = Property.objects.select_for_update().get(pk=prop.pk)
            require_property_agent(prop=locked, agent=actor)
            if action == PropertyTenantRequest.Action.ASSIGN:
                if Tenancy.objects.filter(tenant=tenant, ended_at__isnull=True).exists():
                    raise Conflict("This tenant already has a current tenancy.")
                fields = {
                    "unit": data["unit"].strip(),
                    "lease_start": data["leaseStart"],
                    "next_due_date": data["nextDueDate"],
                }
            else:
                if not Tenancy.objects.filter(
                    property=locked, tenant=tenant, ended_at__isnull=True
                ).exists():
                    raise InvalidTenant("This tenant is not currently assigned to the property.")
                fields = {"unit": "", "lease_start": None, "next_due_date": None}

            tenant_request = PropertyTenantRequest.objects.create(
                property=locked,
                tenant=tenant,
                requested_by=actor,
                action=action,
                **fields,
            )
            from apps.notifications.models import Notification
            from apps.notifications.services import notify

            action_label = "assign" if action == PropertyTenantRequest.Action.ASSIGN else "remove"
            notify(
                recipient_id=locked.landlord_id,
                type=Notification.Type.TENANT_ASSIGNMENT_REQUEST,
                title="Tenant change needs approval",
                message=f"{actor.name} requested to {action_label} {tenant.name} at {locked.title}.",
                data={
                    "tenantAssignmentRequestId": str(tenant_request.pk),
                    "propertyId": str(locked.pk),
                    "tenantId": str(tenant.pk),
                    "tenantName": tenant.name,
                    "action": action,
                },
                dedupe_key=f"tenant-request:{tenant_request.pk}",
            )
            record(
                Action.TENANT_ASSIGNMENT_REQUESTED,
                actor=actor,
                entity=tenant_request,
                metadata={"property_id": str(locked.pk), "tenant_id": str(tenant.pk), "action": action},
                request=request,
            )
    except IntegrityError as exc:
        raise Conflict("A matching tenant request is already pending.") from exc
    return tenant_request


def decide_tenant_change(*, request_id, landlord: User, decision: str, request=None):
    from apps.tenancies.models import Tenancy

    try:
        with transaction.atomic():
            tenant_request = (
                PropertyTenantRequest.objects.select_for_update()
                .select_related("property", "tenant")
                .get(pk=request_id)
            )
            if tenant_request.property.landlord_id != landlord.pk:
                raise PermissionDenied("Only the property landlord can decide this request.")
            if tenant_request.status != PropertyTenantRequest.Status.PENDING:
                raise Conflict("This tenant request has already been decided.")

            prop = Property.objects.select_for_update().get(pk=tenant_request.property_id)
            if decision == "approve":
                if tenant_request.action == PropertyTenantRequest.Action.ASSIGN:
                    Tenancy.objects.create(
                        tenant=tenant_request.tenant,
                        property=prop,
                        unit=tenant_request.unit,
                        lease_start=tenant_request.lease_start,
                        next_due_date=tenant_request.next_due_date,
                    )
                else:
                    ended = Tenancy.objects.filter(
                        property=prop, tenant=tenant_request.tenant, ended_at__isnull=True
                    ).update(ended_at=timezone.now())
                    if not ended:
                        raise Conflict("This tenant no longer has a current tenancy here.")
                tenant_request.status = PropertyTenantRequest.Status.APPROVED
                audit_action = Action.TENANT_ASSIGNMENT_APPROVED
            else:
                tenant_request.status = PropertyTenantRequest.Status.REJECTED
                audit_action = Action.TENANT_ASSIGNMENT_REJECTED

            tenant_request.decided_by = landlord
            tenant_request.decided_at = timezone.now()
            tenant_request.save(update_fields=["status", "decided_by", "decided_at"])
            from apps.notifications.models import Notification

            notification = Notification.objects.filter(
                data__tenantAssignmentRequestId=str(tenant_request.pk),
                recipient=landlord,
            ).first()
            if notification:
                notification.data["requestStatus"] = tenant_request.status
                notification.is_read = True
                notification.read_at = tenant_request.decided_at
                notification.save(update_fields=["data", "is_read", "read_at"])
            from apps.notifications.services import notify

            outcome = "approved" if decision == "approve" else "rejected"
            notify(
                recipient_id=tenant_request.requested_by_id,
                type=Notification.Type.TENANT_ASSIGNMENT_REQUEST,
                title=f"Tenant request {outcome}",
                message=f"Your request to {tenant_request.action} {tenant_request.tenant.name} at {prop.title} was {outcome}.",
                data={
                    "tenantAssignmentRequestId": str(tenant_request.pk),
                    "propertyId": str(prop.pk),
                    "tenantId": str(tenant_request.tenant_id),
                    "tenantName": tenant_request.tenant.name,
                    "action": tenant_request.action,
                    "requestStatus": tenant_request.status,
                },
                dedupe_key=f"tenant-request-decision:{tenant_request.pk}",
            )
            invalidate_on_commit("properties", "tenancies", "tenants", "dashboardStats")
            record(
                audit_action,
                actor=landlord,
                entity=tenant_request,
                metadata={
                    "property_id": str(prop.pk),
                    "tenant_id": str(tenant_request.tenant_id),
                    "action": tenant_request.action,
                },
                request=request,
            )
    except PropertyTenantRequest.DoesNotExist as exc:
        raise InvalidTenantRequest("Tenant request not found.") from exc
    except IntegrityError as exc:
        raise Conflict("The tenant could not be assigned because a current tenancy already exists.") from exc
    return tenant_request


def require_property_agent(*, prop: Property, agent: User) -> None:
    if not PropertyAgentAssignment.objects.filter(
        property=prop, agent=agent, active=True
    ).exists():
        raise PermissionDenied("You are not the active agent for this property.")


class InvalidTenant(Exception):
    pass


class InvalidTenantRequest(Exception):
    pass
