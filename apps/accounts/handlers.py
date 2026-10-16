from apps.common.events import subscribe

from .events import UserRegistered
from .tasks import send_verification_email


@subscribe(UserRegistered)
def queue_verification_email(event: UserRegistered) -> None:
    # Its own task, so an SMTP failure retries only the email, not every handler.
    # The welcome email follows once the address is verified (services.verify_email).
    send_verification_email.delay(event.user_id)
