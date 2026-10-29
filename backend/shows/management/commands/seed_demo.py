import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from shows.models import Cue, Production, Run

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "curtain-up"  # local demo only

# (number, label, page, scene, notes)
CUES = [
    ("1", "Preshow / house to half", 1, "Preshow", ""),
    ("2", "House out", 1, "", "Wait for house manager's clearance"),
    ("5", "Lights up: lighthouse interior, dawn", 2, "1.1 The Lamp Room", ""),
    ("10", "Storm builds upstage", 7, "", ""),
    ("12", "Lightning", 8, "", "On the thunder sound cue, not the line"),
    ("12.5", "Lightning follow", 8, "", ""),
    ("20", "Lamp room: beam sweep", 14, "1.2 The Wreck", ""),
    ("30", "Blackout", 21, "", ""),
    ("31", "Bows", 22, "Curtain call", ""),
    ("32", "House up", 22, "", ""),
]


class Command(BaseCommand):
    help = "Create the demo user and a sample production with a cue list (idempotent)."

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=DEMO_USERNAME)
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        Token.objects.get_or_create(user=user)

        production, _ = Production.objects.get_or_create(
            owner=user,
            name="The Keeper's Light",
            defaults={"venue": "Studio Theatre", "performance_date": datetime.date(2026, 11, 14)},
        )
        if not production.cues.exists():
            Cue.objects.bulk_create(
                Cue(production=production, number=Decimal(n), label=label, page=page, scene=scene, notes=notes)
                for n, label, page, scene, notes in CUES
            )
        Run.objects.get_or_create(production=production, label="Run 1")

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: user '{DEMO_USERNAME}' / '{DEMO_PASSWORD}', "
                f"production '{production.name}' with {production.cues.count()} cues."
            )
        )
