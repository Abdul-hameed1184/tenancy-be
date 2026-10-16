from apps.common.routers import OptionalSlashRouter, optional_slash

from . import views

router = OptionalSlashRouter()
router.register("tenancies", views.TenancyViewSet, basename="tenancy")

urlpatterns = [
    *router.urls,
    *optional_slash(
        "tenants/<uuid:tenant_id>/tenancy", views.TenantTenancyView.as_view(), "tenant-tenancy"
    ),
]
