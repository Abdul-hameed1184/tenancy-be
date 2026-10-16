import dataclasses

from apps.common.events import DomainEvent, event


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class UserRegistered(DomainEvent):
    name = "UserRegistered"
    aggregate_type = "user"

    user_id: str
    role: str

    @property
    def aggregate_id(self) -> str:
        return self.user_id
