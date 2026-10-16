"""
URL table for API v1.

Each domain app exposes its own urls module; this file only composes them. Paths match the
frontend contract (no trailing slash required — see apps.common.routers).
"""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.properties.urls")),
    path("", include("apps.tenancies.urls")),
    path("", include("apps.payments.urls")),
    path("", include("apps.maintenance.urls")),
    path("", include("apps.inspections.urls")),
    path("", include("apps.agents.urls")),
    path("", include("apps.messaging.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.dashboards.urls")),
    path("", include("apps.uploads.urls")),
]
