import dataclasses

from apps.common.events import DomainEvent, event


@dataclasses.dataclass(frozen=True, kw_only=True)
class _VerificationDecision(DomainEvent):
    aggregate_type = "agent"

    agent_id: str
    decided_by_id: str
    trust_score: int

    @property
    def aggregate_id(self) -> str:
        return self.agent_id


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentVerified(_VerificationDecision):
    name = "AgentVerified"


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class AgentVerificationRejected(_VerificationDecision):
    name = "AgentVerificationRejected"
