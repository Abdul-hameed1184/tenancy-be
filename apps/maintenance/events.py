import dataclasses

from apps.common.events import DomainEvent, event


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class MaintenanceCreated(DomainEvent):
    name = "MaintenanceCreated"
    aggregate_type = "maintenance_request"

    request_id: str
    property_id: str
    tenant_id: str
    priority: str

    @property
    def aggregate_id(self) -> str:
        return self.request_id


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class MaintenanceStatusChanged(DomainEvent):
    name = "MaintenanceStatusChanged"
    aggregate_type = "maintenance_request"

    request_id: str
    property_id: str
    tenant_id: str
    issue_type: str
    from_status: str
    to_status: str
    changed_by_id: str

    @property
    def aggregate_id(self) -> str:
        return self.request_id
