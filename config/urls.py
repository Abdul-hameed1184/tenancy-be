from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common import health
from apps.common.views import not_found

urlpatterns = [
    path("health/", health.liveness, name="health-live"),
    path("health/ready/", health.readiness, name="health-ready"),
    # Versioned API. A future v2 gets its own module; apps stay version-agnostic.
    path("api/v1/", include(("config.api_v1", "v1"), namespace="v1")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("admin/", admin.site.urls),
    # Unmatched API paths get a JSON 404 even when DEBUG shows HTML pages elsewhere.
    re_path(r"^api/", not_found),
]

handler404 = "apps.common.views.not_found"
handler500 = "apps.common.views.server_error"
