from django.core.management.base import BaseCommand

from apps.verification import services
from apps.verification.models import IdentityVerification as IV


class Command(BaseCommand):
    help = "Cut portraits for approved verifications that don't have one (e.g. approved before portraits existed)."

    def handle(self, *args, **options):
        done = missing = 0
        for verification in IV.objects.filter(status=IV.Status.APPROVED, portrait="").select_related("user"):
            if services._store_portrait(verification):
                services._publish_portrait(verification)
                done += 1
            else:
                missing += 1
                self.stdout.write(self.style.WARNING(f"No portrait for {verification} — set the box in the admin."))
        self.stdout.write(self.style.SUCCESS(f"Portraits created: {done}. Still missing: {missing}."))
