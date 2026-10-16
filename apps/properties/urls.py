from apps.common.routers import OptionalSlashRouter, optional_slash

from . import views

router = OptionalSlashRouter()
router.register("properties", views.PropertyViewSet, basename="property")

urlpatterns = [
    *router.urls,
    *optional_slash(
        "agents/<uuid:agent_id>/properties/top",
        views.TopAgentPropertiesView.as_view(),
        "agent-top-properties",
    ),
    *optional_slash(
        "properties/<uuid:property_id>/tenant-candidates",
        views.PropertyTenantCandidatesView.as_view(),
        "property-tenant-candidates",
    ),
    *optional_slash(
        "properties/<uuid:property_id>/tenant-requests",
        views.PropertyTenantRequestView.as_view(),
        "property-tenant-requests",
    ),
    *optional_slash(
        "tenant-requests/<uuid:request_id>/decision",
        views.TenantRequestDecisionView.as_view(),
        "tenant-request-decision",
    ),
]
