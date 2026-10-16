from apps.common.routers import optional_slash

from . import views

urlpatterns = [
    *optional_slash("message-contacts", views.PrimaryContactsView.as_view(), "message-contacts"),
    *optional_slash(
        "threads/initialize",
        views.InitializeContactThreadsView.as_view(),
        "thread-initialize",
    ),
    *optional_slash("threads/start", views.StartThreadView.as_view(), "thread-start"),
    *optional_slash(
        "threads/<uuid:thread_id>/read", views.ThreadReadView.as_view(), "thread-read"
    ),
    *optional_slash("threads", views.ThreadListView.as_view(), "thread-list"),
    *optional_slash(
        "threads/<uuid:thread_id>/messages", views.ThreadMessagesView.as_view(), "thread-messages"
    ),
]
