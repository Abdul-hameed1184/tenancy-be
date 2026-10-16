"""
Consistent JSON error responses.

The frontend (src/lib/api/http.ts) displays `message` when it is a string (or the first
item of a string list). Validation errors therefore carry a readable `message` *and* the
per-field detail under `errors`:

    {"message": "Email: Enter a valid email address.", "errors": {"email": ["..."]}}

Every other error is `{"message": "..."}`.
"""

import re

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler as drf_exception_handler

NON_FIELD_KEYS = {"non_field_errors", "__all__", "detail"}
# Error codes the frontend acts on (beyond showing the message), exposed as `code`.
CLIENT_CODES = {"email_not_verified"}


class Conflict(exceptions.APIException):
    """The request is valid but conflicts with current state (e.g. an illegal transition)."""

    status_code = 409
    default_detail = "This action conflicts with the current state of the resource."
    default_code = "conflict"


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(as_serializer_error(exc))
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None:
        # Unhandled exception: let Django log it and render handler500.
        return None

    if isinstance(exc, exceptions.ValidationError):
        errors = response.data if isinstance(response.data, dict) else {"detail": response.data}
        response.data = {"message": _first_message(errors), "errors": errors}
    else:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        response.data = {"message": str(detail or exc)}
        code = getattr(detail, "code", None)
        if code in CLIENT_CODES:
            response.data["code"] = code
    return response


def _first_message(errors: dict) -> str:
    for field, value in errors.items():
        message = _first_leaf(value)
        if message is None:
            continue
        if field in NON_FIELD_KEYS:
            return message
        return f"{_humanize(field)}: {message}"
    return "Invalid input."


def _first_leaf(value) -> str | None:
    if isinstance(value, dict):
        for nested in value.values():
            if (found := _first_leaf(nested)) is not None:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            if (found := _first_leaf(item)) is not None:
                return found
        return None
    return str(value)


def _humanize(field: str) -> str:
    """priceAnnual -> 'Price annual', lease_start -> 'Lease start'."""
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", field).replace("_", " ").lower()
    return words.capitalize()
