from apps.common.routers import OptionalSlashRouter

from . import views

router = OptionalSlashRouter()
router.register("maintenance-requests", views.MaintenanceViewSet, basename="maintenance")

urlpatterns = router.urls
