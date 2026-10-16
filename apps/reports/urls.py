from apps.common.routers import OptionalSlashRouter

from . import views

router = OptionalSlashRouter()
router.register("reports", views.ReportViewSet, basename="report")

urlpatterns = router.urls
