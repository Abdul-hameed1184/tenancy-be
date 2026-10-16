import datetime

import pytest
from rest_framework.exceptions import ValidationError

from apps.common.fields import ContractDateField

field = ContractDateField()


def test_dates_render_as_iso_midnight_utc():
    assert field.to_representation(datetime.date(2026, 9, 27)) == "2026-09-27T00:00:00.000Z"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-27", datetime.date(2026, 9, 27)),
        ("2026-09-27T00:00:00.000Z", datetime.date(2026, 9, 27)),
        # Local midnight in Lagos (UTC+1), as a browser date picker sends it, is still the
        # 27th. A naive UTC .date() would say the 26th.
        ("2026-09-26T23:00:00.000Z", datetime.date(2026, 9, 27)),
        ("2026-09-27T10:00:00+01:00", datetime.date(2026, 9, 27)),
    ],
)
def test_parses_dates_and_datetimes_in_business_timezone(raw, expected):
    assert field.to_internal_value(raw) == expected


@pytest.mark.parametrize("raw", ["27/09/2026", "2026-13-01", "", 20260927, None])
def test_rejects_invalid_input(raw):
    with pytest.raises(ValidationError):
        field.to_internal_value(raw)
