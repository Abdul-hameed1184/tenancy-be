from django.core.management.base import BaseCommand
from apps.payments.tasks import flag_overdue_rent


class Command(BaseCommand):
    help = "Flag overdue rent"

    def handle(self, *args, **options):
        created = flag_overdue_rent()
        self.stdout.write(
            self.style.SUCCESS(
                f"Overdue rent processing completed. "
                f"{created} new notifications created."
            )
        )