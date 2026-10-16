import json
import logging

import pytest

from apps.common.logging import JSONFormatter, RedactingFilter, RequestIdFilter, request_id_var


def emit(msg, *args, **extra):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args or None, None)
    record.__dict__.update(extra)
    RequestIdFilter().filter(record)
    RedactingFilter().filter(record)
    return json.loads(JSONFormatter().format(record))


def test_sensitive_extra_fields_are_redacted():
    out = emit("login", password="hunter2", refresh_token="abc", email="a@b.c")
    assert out["password"] == "[REDACTED]" and out["refresh_token"] == "[REDACTED]"
    assert out["email"] == "a@b.c"


def test_bearer_tokens_are_masked_in_messages_and_args():
    out = emit("header was %s", "Bearer eyJhbGciOi.payload.sig")
    assert "eyJ" not in out["message"] and "[REDACTED]" in out["message"]


def test_nested_dicts_are_scrubbed():
    out = emit("x", context={"headers": {"Authorization": "Bearer abc"}, "path": "/x"})
    assert out["context"] == {"headers": {"Authorization": "[REDACTED]"}, "path": "/x"}


def test_json_lines_carry_request_id():
    token = request_id_var.set("req-123")
    try:
        assert emit("hello")["request_id"] == "req-123"
    finally:
        request_id_var.reset(token)


@pytest.mark.django_db
def test_response_echoes_request_id_and_access_log_is_written(api_client, caplog):
    with caplog.at_level(logging.INFO, logger="pleet.access"):
        response = api_client.get("/health/", HTTP_X_REQUEST_ID="trace-abc")
    assert response["X-Request-ID"] == "trace-abc"
    line = next(r for r in caplog.records if r.name == "pleet.access")
    assert line.getMessage() == "GET /health/ 200" and line.status == 200


@pytest.mark.django_db
def test_malformed_request_id_is_replaced(api_client):
    response = api_client.get("/health/", HTTP_X_REQUEST_ID="bad id\nwith newline")
    assert response["X-Request-ID"] != "bad id\nwith newline"
    assert len(response["X-Request-ID"]) == 32
