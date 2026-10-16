from apps.common.routers import optional_slash

from . import views

urlpatterns = [
    *optional_slash("notifications", views.NotificationListView.as_view(), "notification-list"),
    *optional_slash(
        "notifications/read-all", views.MarkAllReadView.as_view(), "notification-read-all"
    ),
    *optional_slash(
        "notifications/<uuid:notification_id>/read",
        views.MarkReadView.as_view(),
        "notification-read",
    ),
]
