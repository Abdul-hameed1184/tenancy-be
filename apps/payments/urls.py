from apps.common.routers import optional_slash

from . import views

urlpatterns = [
    *optional_slash(
        "tenancies/<uuid:pk>/payments", views.TenancyPaymentsView.as_view(), "tenancy-payments"
    ),
]
