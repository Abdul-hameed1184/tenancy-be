import logging
import re
import time
import uuid

from .logging import request_id_var

access_logger = logging.getLogger("pleet.access")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware:
    """
    Tags each request with an id (the caller's X-Request-ID when well-formed, e.g. from a
    load balancer, otherwise a fresh one). The id is attached to every log line during
    the request and echoed in the response, so one failing request can be traced through
    web logs, the access log and the client's error report.

    Also writes one access-log line per request. The query string is deliberately left
    out: it can carry filters with personal data, and logs outlive their purpose.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            user = getattr(request, "user", None)  # DRF copies its user onto the request
            access_logger.info(
                "%s %s %s",
                request.method,
                request.path,
                response.status_code,
                extra={
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "user_id": str(user.pk) if getattr(user, "is_authenticated", False) else None,
                },
            )
            return response
        finally:
            request_id_var.reset(token)
