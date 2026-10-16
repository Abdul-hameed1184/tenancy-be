import dataclasses

from apps.common.events import DomainEvent, event


@dataclasses.dataclass(frozen=True, kw_only=True)
class _InspectionEvent(DomainEvent):
    aggregate_type = "inspection"

    inspection_id: str
    property_id: str
    tenant_id: str
    agent_id: str
    scheduled_at: str
    actor_id: str

    @property
    def aggregate_id(self) -> str:
        return self.inspection_id


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class InspectionRequested(_InspectionEvent):
    name = "InspectionRequested"


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class InspectionConfirmed(_InspectionEvent):
    name = "InspectionConfirmed"


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class InspectionCompleted(_InspectionEvent):
    name = "InspectionCompleted"


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class InspectionCancelled(_InspectionEvent):
    name = "InspectionCancelled"


EVENT_FOR_ACTION = {
    "confirm": InspectionConfirmed,
    "complete": InspectionCompleted,
    "cancel": InspectionCancelled,
}
