import datetime as dt

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef

from apps.accounts.models import User
from apps.audit.services import Action, record
from apps.common.events import publish
from apps.common.exceptions import Conflict
from apps.properties.selectors import active_assignments
from apps.tenancies.models import Tenancy

from .events import PaymentCreated, PaymentPaid
from .models import PaymentEntry


class NotManagingAgent(Exception):
    pass


def add_one_year(day: dt.date) -> dt.date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 Feb -> 28 Feb of a non-leap year
        return day.replace(year=day.year + 1, day=28)


def log_payment(*, tenancy: Tenancy, agent: User, data: dict, request=None) -> PaymentEntry:
    """
    Append a ledger entry; when it's a paid entry, move the tenancy's next due date forward.

    Concurrency:
    - SELECT ... FOR UPDATE on the tenancy row serialises everyone logging against this
      tenancy, so the read-modify-write of next_due_date can't interleave and lose an update.
    - The partial unique index (tenancy, due_date) WHERE paid rejects a second "paid" for
      the same period, even if two requests were somehow both admitted.

    next_due_date only ever moves forward: logging an old back-payment late must not pull
    the next due date into the past (the literal contract rule, dueDate + 1 year, would).
    """
    try:
        with transaction.atomic():
            locked = (
                Tenancy.objects.select_for_update()
                .filter(pk=tenancy.pk)
                .annotate(
                    managed=Exists(
                        active_assignments().filter(agent=agent, property=OuterRef("property_id"))
                    )
                )
                .get()
            )
            # Re-checked under the lock: the agent may have been replaced since the request
            # passed its permission check.
            if not locked.managed:
                raise NotManagingAgent

            entry = PaymentEntry.objects.create(tenancy=locked, logged_by=agent, **data)
            publish(
                PaymentCreated(
                    payment_id=str(entry.pk),
                    tenancy_id=str(locked.pk),
                    tenant_id=str(locked.tenant_id),
                    status=entry.status,
                    amount=entry.amount,
                    due_date=entry.due_date.isoformat(),
                )
            )
            record(
                Action.PAYMENT_CREATED,
                actor=agent,
                entity=entry,
                metadata={"tenancy_id": str(locked.pk), "status": entry.status},
                request=request,
            )

            if entry.status == PaymentEntry.Status.PAID:
                candidate = add_one_year(entry.due_date)
                previous = locked.next_due_date
                if candidate > previous:
                    locked.next_due_date = candidate
                    locked.save(update_fields=["next_due_date"])
                publish(
                    PaymentPaid(
                        payment_id=str(entry.pk),
                        tenancy_id=str(locked.pk),
                        tenant_id=str(locked.tenant_id),
                        amount=entry.amount,
                        due_date=entry.due_date.isoformat(),
                        next_due_date=locked.next_due_date.isoformat(),
                    )
                )
                record(
                    Action.PAYMENT_MARKED_PAID,
                    actor=agent,
                    entity=entry,
                    metadata={
                        "tenancy_id": str(locked.pk),
                        "next_due_date": locked.next_due_date.isoformat(),
                        "previous_next_due_date": previous.isoformat(),
                    },
                    request=request,
                )
    except IntegrityError as exc:
        raise Conflict("This due date has already been paid.") from exc
    return entry
