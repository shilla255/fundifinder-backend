from django.core.management.base import BaseCommand

from apps.bookings.services import process_due_bookings


class Command(BaseCommand):
    help = "Expire unanswered booking requests and auto-close unconfirmed completed jobs."

    def handle(self, *args, **options):
        counts = process_due_bookings()
        self.stdout.write(f"Expired {counts['expired']}, closed {counts['closed']}.")
