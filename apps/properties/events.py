import dataclasses

from apps.common.events import DomainEvent, event


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentAssigned(DomainEvent):
    name = "AgentAssigned"
    aggregate_type = "property"

    property_id: str
    landlord_id: str
    agent_id: str
    previous_agent_id: str | None
    assignment_id: str

    @property
    def aggregate_id(self) -> str:
        return self.property_id


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentUnassigned(DomainEvent):
    name = "AgentUnassigned"
    aggregate_type = "property"

    property_id: str
    landlord_id: str
    agent_id: str
    assignment_id: str

    @property
    def aggregate_id(self) -> str:
        return self.property_id
