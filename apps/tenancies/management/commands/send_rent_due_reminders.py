
from django.core.management.base import BaseCommand

from apps.payments.tasks import send_rent_due_reminders


class Command(BaseCommand):
    help = "Send rent due reminders"

    def handle(self, *args, **options):
        created = send_rent_due_reminders()
        self.stdout.write(
            self.style.SUCCESS(
                f"Rent due reminders completed. "
                f"{created} new notifications created."
            )
        )