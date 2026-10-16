from apps.common.routers import OptionalSlashRouter

from . import views

router = OptionalSlashRouter()
router.register("inspections", views.InspectionViewSet, basename="inspection")

urlpatterns = router.urls
