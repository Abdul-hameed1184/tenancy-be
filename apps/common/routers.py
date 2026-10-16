"""
The frontend calls paths without a trailing slash (`/auth/login`, `/properties/123`).

Django's default APPEND_SLASH answers an unmatched slash-less URL with a 301 redirect,
which browsers follow as GET, so a POST silently loses its body. Instead, every API route
matches both forms directly.
"""

from django.urls import path
from rest_framework.routers import SimpleRouter


class OptionalSlashRouter(SimpleRouter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = "/?"


def optional_slash(route: str, view, name: str | None = None) -> list:
    """`path()` for non-viewset views, matching `route` and `route/`."""
    return [path(route, view, name=name), path(f"{route}/", view)]
