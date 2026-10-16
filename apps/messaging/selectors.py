from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import (
    Count,
    DateTimeField,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce

from apps.accounts.models import User
from apps.properties.models import Property
from apps.properties.selectors import active_assignments

from .models import Message, MessageThread, ThreadParticipant


def is_participant(user_id, thread_id) -> bool:
    """The single membership check shared by REST views and the WebSocket consumer."""
    return ThreadParticipant.objects.filter(user_id=user_id, thread_id=thread_id).exists()


def threads_for(user) -> QuerySet[MessageThread]:
    """
    Threads the user belongs to, newest activity first, with participantIds aggregated by
    PostgreSQL (ARRAY_AGG) in the same query rather than one query per thread.
    """
    member = ThreadParticipant.objects.filter(thread=OuterRef("pk"), user=user)
    last_read_at = member.values("last_read_at")[:1]
    unread_count = (
        Message.objects.filter(thread=OuterRef("pk"))
        .exclude(sender=user)
        .filter(
            sent_at__gt=Coalesce(
                OuterRef("participant_last_read_at"),
                OuterRef("created_at"),
                output_field=DateTimeField(),
            )
        )
        .order_by()
        .values("thread_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    last_message_preview = Message.objects.filter(thread=OuterRef("pk"))
    last_message_preview = last_message_preview.order_by("-sent_at", "-pk").values("body")[:1]
    return (
        MessageThread.objects.filter(Exists(member))
        .annotate(
            participant_ids=ArrayAgg("memberships__user_id", order_by="memberships__joined_at"),
            participant_last_read_at=Subquery(last_read_at, output_field=DateTimeField()),
            last_message_preview=Subquery(last_message_preview),
        )
        .annotate(
            unread_count=Coalesce(Subquery(unread_count), Value(0), output_field=IntegerField()),
        )
        .order_by("-last_message_at")
    )


def messages_in(thread_id) -> QuerySet[Message]:
    return Message.objects.filter(thread_id=thread_id).order_by("sent_at", "id")


def primary_contacts_for(user: User) -> list[dict]:
    if user.is_tenant:
        properties = Property.objects.filter(
            Q(tenancies__tenant=user, tenancies__ended_at__isnull=True)
            | Q(inspections__tenant=user, inspections__status__in=["requested", "confirmed"])
        ).distinct()
    elif user.is_agent:
        properties = Property.objects.filter(
            agent_assignments__agent=user, agent_assignments__active=True
        )
    elif user.is_landlord:
        properties = Property.objects.filter(landlord=user)
    else:
        return []

    contacts = {}
    assignments = active_assignments()
    for prop in properties.select_related("landlord").order_by("title"):
        agent = assignments.filter(property=prop).select_related("agent").first()
        if user.is_tenant:
            recipient = agent.agent if agent else prop.landlord
            people = [(recipient, prop)]
        elif user.is_agent:
            tenants = User.objects.filter(
                tenancies__property=prop, tenancies__ended_at__isnull=True, role=User.Role.TENANT
            ).order_by("name")
            people = [(prop.landlord, prop), *((tenant, prop) for tenant in tenants)]
        else:
            tenants = User.objects.filter(
                tenancies__property=prop, tenancies__ended_at__isnull=True, role=User.Role.TENANT
            ).order_by("name")
            people = ([(agent.agent, prop)] if agent else []) + [
                (tenant, prop) for tenant in tenants
            ]

        for recipient, contact_property in people:
            key = (recipient.pk, contact_property.pk)
            if recipient.pk != user.pk:
                contacts[key] = {
                    "id": str(recipient.pk),
                    "name": recipient.name,
                    "role": recipient.role,
                    "propertyId": str(contact_property.pk),
                    "propertyTitle": contact_property.title,
                }
    return list(contacts.values())


def can_start_thread(*, user: User, recipient_id, property_id) -> bool:
    return any(
        contact["id"] == str(recipient_id) and contact["propertyId"] == str(property_id)
        for contact in primary_contacts_for(user)
    )
