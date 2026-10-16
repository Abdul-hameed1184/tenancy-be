import dataclasses

from apps.common.events import DomainEvent, event


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class PaymentCreated(DomainEvent):
    name = "PaymentCreated"
    aggregate_type = "tenancy"

    payment_id: str
    tenancy_id: str
    tenant_id: str
    status: str
    amount: int
    due_date: str

    @property
    def aggregate_id(self) -> str:
        return self.tenancy_id


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class PaymentPaid(DomainEvent):
    name = "PaymentPaid"
    aggregate_type = "tenancy"

    payment_id: str
    tenancy_id: str
    tenant_id: str
    amount: int
    due_date: str
    next_due_date: str

    @property
    def aggregate_id(self) -> str:
        return self.tenancy_id
