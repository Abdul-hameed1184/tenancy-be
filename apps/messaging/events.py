import dataclasses

from apps.common.events import DomainEvent, event


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class MessageSent(DomainEvent):
    name = "MessageSent"
    aggregate_type = "thread"

    message_id: str
    thread_id: str
    sender_id: str
    recipient_ids: list[str]

    @property
    def aggregate_id(self) -> str:
        return self.thread_id
