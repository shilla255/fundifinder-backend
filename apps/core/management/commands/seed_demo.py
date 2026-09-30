import random
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Avg, Count
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking, Review
from apps.catalog.models import ServiceCategory
from apps.core.geo import make_point
from apps.core.placeholder_art import id_card as work_photo_card
from apps.core.placeholder_art import work_photo
from apps.fundis.models import FundiProfile, FundiService, WorkPhoto

PASSWORD = "demo-pass-123"
PHOTOS_PER_FUNDI = 5

# (handle, name, business, (lat, lng), area, district, region, years, response minutes, bio,
#  [(category slug, pricing, price)])
FUNDIS = [
    ("juma", "Juma Hassan", "Juma Electric", (-6.7836, 39.2208), "Sinza, near Mori", "Kinondoni",
     "Dar es Salaam", 8, 12, "Licensed electrician. House wiring, sockets, DB boards and solar.",
     [("electrical", "callout", 15000), ("solar-installation", "quote", None)]),
    ("neema", "Neema Mushi", "Neema Plumbing Works", (-6.7711, 39.2489), "Mwenge, near the market",
     "Kinondoni", "Dar es Salaam", 6, 20, "Leaks, blocked drains, water tanks and bathroom fittings.",
     [("plumbing", "callout", 10000)]),
    ("baraka", "Baraka Mollel", "Baraka Auto Garage", (-6.8161, 39.2803), "Kariakoo", "Ilala",
     "Dar es Salaam", 11, 45, "Engine diagnostics, brakes and suspension for cars and bodaboda.",
     [("mechanics", "quote", None), ("motorcycle-mechanics", "hourly", 8000)]),
    ("rehema", "Rehema Kweka", "Rehema Rangi & Design", (-6.7602, 39.2721), "Mikocheni B", "Kinondoni",
     "Dar es Salaam", 5, 25, "Interior and exterior painting, gypsum and decorative finishes.",
     [("painting", "fixed", 35000)]),
    ("hamisi", "Hamisi Juma", "Hamisi Useremala", (-6.8235, 39.2695), "Upanga", "Ilala",
     "Dar es Salaam", 14, 60, "Custom furniture, kitchen cabinets, doors and roofing timber.",
     [("carpentry", "quote", None)]),
    ("upendo", "Upendo Mrema", "Upendo Cool Services", (-6.7496, 39.2767), "Mbezi Beach", "Kinondoni",
     "Dar es Salaam", 7, 18, "AC installation and servicing, fridges and cold rooms.",
     [("ac-refrigeration", "callout", 25000)]),
    ("salim", "Salim Omari", "Salim Welding Works", (-6.8567, 39.2555), "Temeke Mwisho", "Temeke",
     "Dar es Salaam", 9, 35, "Gates, window grills, burglar bars and steel structures.",
     [("welding", "quote", None)]),
    ("grace", "Grace Lyimo", "Grace Tech Repairs", (-6.7924, 39.2083), "Ubungo Plaza", "Ubungo",
     "Dar es Salaam", 4, 15, "Phones, TVs, radios and home electronics. Quick turnaround.",
     [("electronics-repair", "fixed", 10000)]),
    ("elia", "Elia Massawe", "Elia Construction", (-6.8420, 39.2280), "Tabata", "Ilala",
     "Dar es Salaam", 12, 90, "Block work, plastering, tiling and foundations.",
     [("masonry", "fixed", 40000)]),
    ("amani", "Amani Kileo", "Amani Solar Solutions", (-3.3869, 36.6830), "Njiro", "Arusha",
     "Arusha", 6, 30, "Solar systems for homes and shops, batteries and inverters.",
     [("solar-installation", "quote", None), ("electrical", "callout", 12000)]),
    ("zawadi", "Zawadi Nyirenda", "Zawadi Plumbers", (-6.1659, 35.7516), "Area D", "Dodoma",
     "Dodoma", 5, 40, "Plumbing for new houses, water pumps and tank installation.",
     [("plumbing", "callout", 8000)]),
    ("musa", "Musa Abdallah", "Musa Bodaboda Garage", (-2.5164, 32.9175), "Kirumba", "Ilemela",
     "Mwanza", 10, 22, "Bodaboda and bajaji repairs, spares available.",
     [("motorcycle-mechanics", "hourly", 6000)]),
]

CLIENTS = [
    ("client", "Asha Client", "+255712000200"),
    ("fatuma", "Fatuma Ally", "+255712000201"),
    ("peter", "Peter Mwakyusa", "+255712000202"),
    ("halima", "Halima Said", "+255712000203"),
    ("john", "John Kimaro", "+255712000204"),
]

# (rating, comment) — a mix of Kiswahili and English, as real clients write.
REVIEWS = [
    (5, "Kazi nzuri sana, amefika kwa wakati na bei nafuu. Namshauri kila mtu."),
    (5, "Very professional and clean work. Will call again."),
    (5, "Alinieleza tatizo vizuri kabla ya kuanza. Fundi wa kuaminika."),
    (4, "Good job overall, came a bit late but finished the same day."),
    (5, "Mchapakazi kweli! Kazi imekamilika ndani ya saa mbili."),
    (4, "Bei nzuri na huduma nzuri. Nitamtumia tena."),
    (5, "Honest pricing and he explained everything. Highly recommended."),
    (3, "Kazi ni sawa ila alichelewa kidogo."),
    (5, "Fast response and quality work. Asante sana!"),
    (4, "Nice work, very polite and tidy."),
    (5, "Amefanya kazi kwa umakini mkubwa, nyumba iko safi baada ya kazi."),
    (5, ""),
    (4, ""),
]

JOBS = {
    "electrical": ["Fix sockets in the sitting room", "Replace the DB board breaker", "Wiring for a new room"],
    "solar-installation": ["Install 200W solar panel and battery", "Solar inverter not charging"],
    "plumbing": ["Kitchen sink leaking", "Blocked toilet", "Install a new water tank"],
    "mechanics": ["Car brakes making noise", "Engine check light is on"],
    "motorcycle-mechanics": ["Bodaboda won't start", "Change chain and sprocket"],
    "painting": ["Paint two bedrooms", "Exterior wall painting"],
    "carpentry": ["Make kitchen cabinets", "Repair wardrobe doors"],
    "ac-refrigeration": ["AC servicing (2 units)", "Fridge not cooling"],
    "welding": ["Make a new front gate", "Window grills for 4 windows"],
    "electronics-repair": ["TV has no picture", "Phone screen replacement"],
    "masonry": ["Tile the bathroom floor", "Plaster a boundary wall"],
}

CAPTIONS = {
    "electrical": ["New DB board installed", "Wiring for a new house", "Outdoor security lights"],
    "solar-installation": ["Rooftop solar panels", "Battery and inverter setup"],
    "plumbing": ["Bathroom fittings", "New water tank connection", "Kitchen sink replacement"],
    "mechanics": ["Engine overhaul", "Brake service"],
    "motorcycle-mechanics": ["Bodaboda engine repair", "Full service"],
    "painting": ["Sitting room repaint", "Exterior finish", "Feature wall"],
    "carpentry": ["Kitchen cabinets", "Custom wardrobe", "Dining table"],
    "ac-refrigeration": ["Split AC installation", "AC servicing"],
    "welding": ["Front gate", "Window grills", "Steel staircase"],
    "electronics-repair": ["TV board repair", "Phone screen replacement"],
    "masonry": ["Bathroom tiling", "Boundary wall", "Plastering"],
}

# CC-licensed photos from Flickr via LoremFlickr (keyword search). Falls back to generated art.
PHOTO_KEYWORDS = {
    "electrical": "electrician,wiring",
    "solar-installation": "solar,panel",
    "plumbing": "plumbing,pipes",
    "mechanics": "mechanic,car",
    "motorcycle-mechanics": "motorcycle,repair",
    "painting": "painting,wall",
    "carpentry": "carpentry,wood",
    "ac-refrigeration": "airconditioner",
    "welding": "welding",
    "electronics-repair": "electronics,repair",
    "masonry": "bricklaying,construction",
}


class Command(BaseCommand):
    help = "DEVELOPMENT ONLY: create verified demo fundis (with photos and reviews) and demo clients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--offline", action="store_true",
            help="Don't download stock photos; use generated placeholder art.",
        )
        parser.add_argument(
            "--reset-photos", action="store_true",
            help="Replace existing demo work photos and cover photos.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DJANGO_DEBUG=true.")
        call_command("seed_categories")
        self.offline = options["offline"]
        self.downloads_failed = 0
        rng = random.Random(42)

        clients = [self._user(f"{h}@demo.fundifinder", n, p) for h, n, p in CLIENTS]

        fundis = []
        for i, (handle, name, business, (lat, lng), area, district, region, years, response, bio,
                services) in enumerate(FUNDIS):
            user = self._user(f"{handle}@demo.fundifinder", name, f"+2557120001{i + 1:02d}")
            user.onboarding_role = User.Role.FUNDI
            user.save(update_fields=["onboarding_role"])
            self._identity(user, i, reset=options["reset_photos"])
            profile, _ = FundiProfile.objects.update_or_create(
                user=user,
                defaults={
                    "business_name": business,
                    "bio": bio,
                    "years_experience": years,
                    "base_location": make_point(lat, lng),
                    "service_radius_km": 20,
                    "area_text": area,
                    "district": district,
                    "region": region,
                    "status": FundiProfile.Status.ACTIVE,
                    "activated_at": timezone.now() - timedelta(days=30 + i * 17),
                    "is_available": i % 5 != 4,  # a couple are busy right now
                    "avg_response_minutes": response,
                    "profile_views": rng.randint(40, 900),
                },
            )
            for order, (slug, pricing, price) in enumerate(services):
                FundiService.objects.update_or_create(
                    fundi=profile,
                    category=ServiceCategory.objects.get(slug=slug),
                    defaults={"pricing_type": pricing, "starting_price_tzs": price, "is_primary": order == 0},
                )
            self._photos(profile, [s[0] for s in services], seed=i, reset=options["reset_photos"])
            fundis.append((profile, [s[0] for s in services]))
            self.stdout.write(f"  ✓ {business}")

        self._reviews(fundis, clients, rng)
        self._staff_demo(fundis, clients)

        if self.downloads_failed:
            self.stdout.write(self.style.WARNING(
                f"{self.downloads_failed} stock photos couldn't be downloaded; used generated art instead."
            ))
        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready: {len(fundis)} fundis, {len(clients)} clients. Log in with any demo email "
            f"(e.g. client@demo.fundifinder, juma@demo.fundifinder, staff: admin@demo.fundifinder) "
            f"and password '{PASSWORD}'."
        ))

    def _user(self, email, name, phone):
        user = User.objects.filter(email=email).first() or User.objects.create_user(email=email)
        user.full_name = name
        user.phone_number = phone
        user.set_password(PASSWORD)
        user.save()
        return user

    # --- identity ---------------------------------------------------------------------

    def _identity(self, user, index, reset):
        """Approved ID document with a mock card, so the avatar comes through the real
        portrait pipeline (mostly NIDA; a couple of driving licences and passports)."""
        from datetime import date

        from apps.verification import services as verification
        from apps.verification.models import IdentityVerification as IV

        approved = IV.objects.filter(user=user, status=IV.Status.APPROVED).first()
        if approved and approved.portrait and user.portrait and not reset:
            return
        # Start this demo person's identity from scratch.
        IV.objects.filter(user=user).delete()
        user.identity_status = User.IdentityStatus.UNVERIFIED
        user.portrait = ""
        user.save(update_fields=["identity_status", "portrait"])

        doc = {3: "driving_licence", 7: "passport"}.get(index, "nida")
        dob = date(1980 + index, 1 + index % 12, 1 + (index * 3) % 27)
        number = {
            "nida": f"{dob:%Y%m%d}{5000 + index:05d}{index:05d}{17 + index:02d}",
            "driving_licence": f"40{index:02d}{123456 + index:06d}",
            "passport": f"AB{1234560 + index:07d}",
        }[doc]
        card = work_photo_card(doc, user.full_name, number, seed=index)
        submission = verification.submit(
            user,
            document_type=doc,
            document_number=number,
            full_name=user.full_name,
            date_of_birth=dob,
            id_front_image=ContentFile(card, name="front.jpg"),
            selfie_image=ContentFile(card, name="selfie.jpg"),
        )
        verification.approve(submission, reviewer=None)

    # --- staff console demo ---------------------------------------------------------------

    def _staff_demo(self, fundis, clients):
        """A staff account, two fundi applicants waiting for ID review, and one open dispute."""
        from datetime import date

        from apps.bookings.models import Booking, BookingEvent
        from apps.verification import services as verification
        from apps.verification.models import IdentityVerification as IV

        admin = self._user("admin@demo.fundifinder", "Admin FundiFinder", "+255712000300")
        admin.is_staff = True
        admin.save(update_fields=["is_staff"])

        applicants = [
            ("shabani", "Shabani Mfinanga", "Shabani Tiles & Masonry", "nida", "19880603123450000321", date(1988, 6, 3), 20),
            ("mwanaidi", "Mwanaidi Said", "Mwanaidi Tailoring & Repairs", "passport", "AB7654321", date(1992, 11, 9), 21),
        ]
        for handle, name, business, doc, number, dob, seed in applicants:
            user = self._user(f"{handle}@demo.fundifinder", name, f"+2557120004{seed:02d}")
            user.onboarding_role = User.Role.FUNDI
            user.save(update_fields=["onboarding_role"])
            FundiProfile.objects.update_or_create(
                user=user,
                defaults={"business_name": business, "base_location": make_point(-6.80, 39.25), "area_text": "Kinondoni",
                          "region": "Dar es Salaam", "status": FundiProfile.Status.ACTIVE},
            )
            if IV.objects.filter(user=user, status=IV.Status.PENDING).exists():
                continue
            IV.objects.filter(user=user).delete()
            user.identity_status = User.IdentityStatus.UNVERIFIED
            user.save(update_fields=["identity_status"])
            card = work_photo_card(doc, name, number, seed=seed)
            verification.submit(
                user, document_type=doc, document_number=number, full_name=name, date_of_birth=dob,
                id_front_image=ContentFile(card, name="front.jpg"), selfie_image=ContentFile(card, name="selfie.jpg"),
            )

        profile, _ = fundis[1]  # Neema Plumbing Works
        if not Booking.objects.filter(fundi=profile, status=Booking.Status.DISPUTED).exists():
            booking = Booking.objects.create(
                client=clients[2], fundi=profile, category=profile.services.first().category,
                description="Water tank still leaking after repair", job_location=profile.base_location,
                job_address=profile.area_text, status=Booking.Status.DISPUTED, quoted_price_tzs=40000,
                dispute_reason="The leak came back the next day and the fundi is not answering.",
                payment_status=Booking.PaymentStatus.DISPUTED,
            )
            BookingEvent.objects.create(booking=booking, from_status="completed", to_status="disputed", actor=clients[2],
                                        actor_role="client", note=booking.dispute_reason)
        self.stdout.write("  ✓ Staff demo: admin@demo.fundifinder, 2 ID applications, 1 dispute")

    # --- photos -------------------------------------------------------------------------

    def _photos(self, profile, slugs, seed, reset):
        if profile.work_photos.exists() and not reset:
            return
        for old in profile.work_photos.all():
            old.image.delete(save=False)
            old.thumbnail.delete(save=False)
            old.delete()
        if profile.cover_photo:
            profile.cover_photo.delete(save=False)

        for n in range(PHOTOS_PER_FUNDI):
            slug = slugs[n % len(slugs)]
            captions = CAPTIONS.get(slug) or ["Recent work"]
            data = self._photo_bytes(slug, seed * 10 + n)
            photo = WorkPhoto(
                fundi=profile,
                caption=captions[n % len(captions)],
                category=ServiceCategory.objects.get(slug=slug),
                sort_order=n,
            )
            photo.image.save(f"{profile.pk.hex[:8]}-{n}.jpg", ContentFile(data), save=False)
            photo.save()
        cover = self._photo_bytes(slugs[0], seed * 10 + 99)
        profile.cover_photo.save(f"{profile.pk.hex[:8]}-cover.jpg", ContentFile(cover), save=True)

    def _photo_bytes(self, slug, seed) -> bytes:
        if not self.offline and slug in PHOTO_KEYWORDS:
            url = f"https://loremflickr.com/1200/900/{PHOTO_KEYWORDS[slug]}?lock={seed + 1}"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "FundiFinder-seed/1.0"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    if response.headers.get_content_type().startswith("image/"):
                        return response.read()
            except Exception:  # noqa: BLE001 — any network problem means "use the fallback"
                pass
            self.downloads_failed += 1
            if self.downloads_failed >= 3:
                self.offline = True  # don't wait on every photo when the network is clearly down
        return work_photo(slug, seed)

    # --- bookings and reviews -----------------------------------------------------------

    def _reviews(self, fundis, clients, rng):
        # Start over so re-running doesn't pile up duplicate history.
        Booking.objects.filter(client__in=clients, fundi__in=[f for f, _ in fundis]).delete()
        now = timezone.now()
        for index, (profile, slugs) in enumerate(fundis):
            count = [7, 5, 4, 6, 3, 5, 2, 4, 3, 2, 1, 0][index % 12]
            for n in range(count):
                slug = slugs[n % len(slugs)]
                rating, comment = REVIEWS[(index * 3 + n) % len(REVIEWS)]
                created = now - timedelta(days=rng.randint(3, 120), hours=rng.randint(0, 20))
                client = clients[(index + n) % len(clients)]
                price = rng.choice([15000, 25000, 40000, 60000, 85000, 120000])
                booking = Booking.objects.create(
                    client=client,
                    fundi=profile,
                    category=ServiceCategory.objects.get(slug=slug),
                    description=rng.choice(JOBS.get(slug, ["General repairs"])),
                    job_location=profile.base_location,
                    job_address=profile.area_text,
                    status=Booking.Status.CLOSED,
                    quoted_price_tzs=price,
                    final_price_tzs=price,
                    payment_status=Booking.PaymentStatus.PAID_CASH,
                )
                responded = created + timedelta(minutes=rng.randint(5, 60))
                closed = responded + timedelta(hours=rng.randint(3, 30))
                Booking.objects.filter(pk=booking.pk).update(
                    created_at=created, responded_at=responded, started_at=responded,
                    completed_at=closed, closed_at=closed,
                )
                review = Review.objects.create(
                    booking=booking, fundi=profile, client=client, rating=rating, comment=comment
                )
                Review.objects.filter(pk=review.pk).update(created_at=closed + timedelta(hours=2))

            stats = Review.objects.filter(fundi=profile).aggregate(avg=Avg("rating"), count=Count("id"))
            FundiProfile.objects.filter(pk=profile.pk).update(
                rating_avg=round(stats["avg"] or 0, 2),
                rating_count=stats["count"],
                completed_jobs_count=Booking.objects.filter(
                    fundi=profile, status=Booking.Status.CLOSED
                ).count() + rng.randint(5, 40),  # jobs done before joining FundiFinder
            )
