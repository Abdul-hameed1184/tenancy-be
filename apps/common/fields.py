import datetime as dt
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


@extend_schema_field(OpenApiTypes.DATETIME)
class ContractDateField(serializers.Field):
    """
    A calendar date (lease start, due date) in the contract's ISO-8601 shape.

    Output: "2026-09-27T00:00:00.000Z". The contract types every date as an ISO string and
    the frontend parses them with `new Date()`; midnight UTC keeps the calendar day stable
    for any client timezone it formats in.

    Input: "2026-09-27" or any ISO datetime. Datetimes are converted to the business
    timezone *before* taking the date. A date picker in Lagos sends local midnight as
    "2026-09-26T23:00:00Z", and a naive UTC .date() would land on the previous day.
    """

    default_error_messages = {"invalid": "Enter a valid date (YYYY-MM-DD or ISO-8601)."}

    def to_representation(self, value: dt.date) -> str:
        return f"{value.isoformat()}T00:00:00.000Z"

    def to_internal_value(self, data) -> dt.date:
        if isinstance(data, dt.datetime):
            return self._localize(data)
        if isinstance(data, dt.date):
            return data
        if not isinstance(data, str):
            self.fail("invalid")
        text = data.strip()
        try:
            if (parsed_date := parse_date(text)) is not None:
                return parsed_date
            if (parsed := parse_datetime(text.replace("Z", "+00:00"))) is not None:
                return self._localize(parsed)
        except ValueError:
            pass
        self.fail("invalid")

    @staticmethod
    def _localize(value: dt.datetime) -> dt.date:
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(ZoneInfo(settings.PLEET_BUSINESS_TIME_ZONE)).date()
