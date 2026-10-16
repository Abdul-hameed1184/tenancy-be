from apps.common.routers import optional_slash

from . import views

urlpatterns = [
    *optional_slash("agents", views.AgentListView.as_view(), "agent-list"),
    *optional_slash("agents/<uuid:agent_id>", views.AgentDetailView.as_view(), "agent-detail"),
    *optional_slash(
        "admin/verifications", views.PendingVerificationsView.as_view(), "verification-list"
    ),
    *optional_slash(
        "admin/verifications/<uuid:agent_id>",
        views.VerificationDecisionView.as_view(),
        "verification-decision",
    ),
]
