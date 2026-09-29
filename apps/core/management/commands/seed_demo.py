from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.catalog.models import ServiceCategory
from apps.core.geo import make_point
from apps.fundis.models import FundiProfile, FundiService

PASSWORD = "demo-pass-123"

# (email, name, phone, business, (lat, lng), area, [(category slug, pricing, price)])
FUNDIS = [
    ("juma@demo.fundifinder", "Juma Hassan", "+255712000101", "Juma Electric",
     (-6.7836, 39.2208), "Sinza, near Mori", [("electrical", "callout", 15000), ("solar-installation", "quote", None)]),
    ("neema@demo.fundifinder", "Neema Mushi", "+255712000102", "Neema Plumbing Works",
     (-6.7711, 39.2489), "Mwenge, near the market", [("plumbing", "callout", 10000)]),
    ("baraka@demo.fundifinder", "Baraka Mollel", "+255712000103", "Baraka Auto Garage",
     (-6.8161, 39.2803), "Kariakoo", [("mechanics", "quote", None), ("motorcycle-mechanics", "hourly", 8000)]),
]


class Command(BaseCommand):
    help = "DEVELOPMENT ONLY: create verified demo fundis in Dar es Salaam and a demo client."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DJANGO_DEBUG=true.")
        call_command("seed_categories")

        for email, name, phone, business, (lat, lng), area, services in FUNDIS:
            user = self._user(email, name, phone)
            user.identity_status = User.IdentityStatus.VERIFIED
            user.save(update_fields=["identity_status"])
            profile, _ = FundiProfile.objects.update_or_create(
                user=user,
                defaults={
                    "business_name": business,
                    "base_location": make_point(lat, lng),
                    "service_radius_km": 15,
                    "area_text": area,
                    "district": "Kinondoni" if lat > -6.8 else "Ilala",
                    "region": "Dar es Salaam",
                    "status": FundiProfile.Status.ACTIVE,
                    "is_available": True,
                },
            )
            for i, (slug, pricing, price) in enumerate(services):
                FundiService.objects.update_or_create(
                    fundi=profile,
                    category=ServiceCategory.objects.get(slug=slug),
                    defaults={"pricing_type": pricing, "starting_price_tzs": price, "is_primary": i == 0},
                )

        self._user("client@demo.fundifinder", "Asha Client", "+255712000200")
        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready. Log in with any demo email (e.g. client@demo.fundifinder, "
            f"juma@demo.fundifinder) and password '{PASSWORD}'."
        ))

    def _user(self, email, name, phone):
        user = User.objects.filter(email=email).first() or User.objects.create_user(email=email)
        user.full_name = name
        user.phone_number = phone
        user.set_password(PASSWORD)
        user.save()
        return user
