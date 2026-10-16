
from django.core.management.base import BaseCommand

from apps.payments.tasks import send_rent_due_reminders


class Command(BaseCommand):
    help = "Create notifications for rent due within seven days"

    def handle(self, *args, **options):
        created = send_rent_due_reminders()

        self.stdout.write(
            self.style.SUCCESS(
                f"Rent due reminder job completed. "
                f"Notifications created: {created}"
            )
        )
