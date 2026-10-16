import dataclasses

from apps.common.events import DomainEvent, event


@event
@dataclasses.dataclass(frozen=True, kw_only=True)
class ReportResolved(DomainEvent):
    name = "ReportResolved"
    aggregate_type = "report"

    report_id: str
    reported_by_id: str
    resolved_by_id: str

    @property
    def aggregate_id(self) -> str:
        return self.report_id
