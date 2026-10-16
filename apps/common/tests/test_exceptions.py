from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions

from apps.common.exceptions import Conflict, exception_handler


def handle(exc):
    return exception_handler(exc, context={})


def test_field_validation_error_has_readable_message_and_field_detail():
    response = handle(exceptions.ValidationError({"priceAnnual": ["Must be positive."]}))
    assert response.status_code == 400
    assert response.data == {
        "message": "Price annual: Must be positive.",
        "errors": {"priceAnnual": ["Must be positive."]},
    }


def test_non_field_validation_error_message_has_no_field_prefix():
    response = handle(exceptions.ValidationError({"non_field_errors": ["Dates overlap."]}))
    assert response.data["message"] == "Dates overlap."


def test_list_validation_error_is_wrapped():
    response = handle(exceptions.ValidationError(["Bad input."]))
    assert response.data["message"] == "Bad input."


def test_nested_validation_error_finds_first_leaf():
    response = handle(exceptions.ValidationError({"photos": {"0": ["Enter a valid URL."]}}))
    assert response.data["message"] == "Photos: Enter a valid URL."


def test_django_validation_error_is_converted():
    response = handle(DjangoValidationError({"email": ["Taken."]}))
    assert response.status_code == 400
    assert response.data["message"] == "Email: Taken."


def test_not_found_and_permission_errors_use_message_key():
    assert handle(Http404()).data == {"message": "Not found."}
    denied = handle(exceptions.PermissionDenied())
    assert denied.status_code == 403
    assert denied.data == {"message": "You do not have permission to perform this action."}


def test_conflict_is_409():
    response = handle(Conflict("Inspection is already completed."))
    assert response.status_code == 409
    assert response.data == {"message": "Inspection is already completed."}


def test_unhandled_exception_returns_none_for_django_to_render_500():
    assert handle(RuntimeError("boom")) is None
