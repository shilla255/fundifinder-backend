from django.core.management.base import BaseCommand

from apps.catalog.models import ServiceCategory

# (slug, English, Kiswahili, icon, [subcategories]).
# Swahili names should be reviewed by a native speaker before launch.
CATEGORIES = [
    ("electrical", "Electrical", "Umeme", "bolt", [
        ("electrical-wiring", "House wiring", "Uwekaji nyaya za umeme", "cable"),
        ("solar-installation", "Solar installation", "Ufungaji wa sola", "sun"),
    ]),
    ("plumbing", "Plumbing", "Mabomba", "droplet", []),
    ("mechanics", "Vehicle mechanics", "Ufundi magari", "car", [
        ("motorcycle-mechanics", "Motorcycle / bodaboda", "Ufundi pikipiki", "bike"),
    ]),
    ("carpentry", "Carpentry", "Useremala", "hammer", []),
    ("masonry", "Masonry", "Uashi", "brick", []),
    ("painting", "Painting", "Upakaji rangi", "brush", []),
    ("welding", "Welding", "Uchomeleaji", "flame", []),
    ("ac-refrigeration", "AC & refrigeration", "Viyoyozi na friji", "snowflake", []),
    ("electronics-repair", "Electronics repair", "Ufundi vifaa vya kielektroniki", "cpu", []),
]


class Command(BaseCommand):
    help = "Create or update the starter service categories (idempotent)."

    def handle(self, *args, **options):
        for order, (slug, en, sw, icon, children) in enumerate(CATEGORIES):
            parent, _ = ServiceCategory.objects.update_or_create(
                slug=slug,
                defaults={"name_en": en, "name_sw": sw, "icon": icon, "sort_order": order},
            )
            for child_order, (c_slug, c_en, c_sw, c_icon) in enumerate(children):
                ServiceCategory.objects.update_or_create(
                    slug=c_slug,
                    defaults={
                        "parent": parent,
                        "name_en": c_en,
                        "name_sw": c_sw,
                        "icon": c_icon,
                        "sort_order": child_order,
                    },
                )
        self.stdout.write(self.style.SUCCESS(f"Seeded {ServiceCategory.objects.count()} categories."))
