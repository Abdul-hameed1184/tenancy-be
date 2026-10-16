from apps.common.routers import optional_slash

from . import views

urlpatterns = [
    *optional_slash("agents/<uuid:agent_id>/stats", views.AgentStatsView.as_view(), "agent-stats"),
    *optional_slash(
        "landlords/<uuid:landlord_id>/stats", views.LandlordStatsView.as_view(), "landlord-stats"
    ),
]
