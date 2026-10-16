from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import Action, record
from apps.common.cache import invalidate_on_commit
from apps.common.events import publish
from apps.common.exceptions import Conflict

from .events import AgentVerificationRejected, AgentVerified
from .models import AgentProfile

VERIFIED_TRUST_FLOOR = 80


def decide_verification(*, agent_id, decision: str, admin: User, request=None) -> AgentProfile:
    """
    Approve or reject a pending verification.

    The profile row is locked so two admins deciding at the same moment can't both act
    (and emit two contradictory events). On approval, trust_score = GREATEST(score, 80) is
    computed by PostgreSQL from the locked row's current value.
    """
    with transaction.atomic():
        profile = AgentProfile.objects.select_for_update().filter(user_id=agent_id).first()
        if profile is None:
            raise AgentProfile.DoesNotExist
        if profile.verification_status != AgentProfile.VerificationStatus.PENDING:
            raise Conflict(
                f"Only pending verifications can be decided (this one is "
                f"{profile.verification_status})."
            )

        verified = decision == AgentProfile.VerificationStatus.VERIFIED
        changes = {
            "verification_status": decision,
            "reviewed_by": admin,
            "reviewed_at": timezone.now(),
            "updated_at": timezone.now(),
        }
        if verified:
            changes["trust_score"] = Greatest(F("trust_score"), Value(VERIFIED_TRUST_FLOOR))
        AgentProfile.objects.filter(pk=profile.pk).update(**changes)
        invalidate_on_commit("agents")
        profile.refresh_from_db()

        event_cls = AgentVerified if verified else AgentVerificationRejected
        publish(
            event_cls(
                agent_id=str(profile.user_id),
                decided_by_id=str(admin.pk),
                trust_score=profile.trust_score,
            )
        )
        record(
            Action.AGENT_VERIFIED if verified else Action.AGENT_VERIFICATION_REJECTED,
            actor=admin,
            entity_type="agent",
            entity_id=str(profile.user_id),
            metadata={"trust_score": profile.trust_score},
            request=request,
        )
    return profile
