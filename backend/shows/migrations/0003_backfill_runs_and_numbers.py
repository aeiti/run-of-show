from decimal import Decimal, InvalidOperation

from django.db import migrations
from django.db.models import Min


def number_or_fail(cue):
    try:
        value = Decimal(cue.number.strip())
    except InvalidOperation:
        value = None
    if value is None or not value.is_finite() or value <= 0:
        raise ValueError(
            f"Cue id={cue.id} in production id={cue.production_id} has number {cue.number!r}, "
            "which is not a positive decimal. Fix it before migrating."
        )
    return value


def forwards(apps, schema_editor):
    Cue = apps.get_model("shows", "Cue")
    CueEvent = apps.get_model("shows", "CueEvent")
    Run = apps.get_model("shows", "Run")

    # Char cue numbers -> decimal. Duplicates within a production would break
    # the new unique constraint in 0004, so catch them here with a clear message.
    seen = {}
    for cue in Cue.objects.all():
        value = number_or_fail(cue)
        key = (cue.production_id, value)
        if key in seen:
            raise ValueError(
                f"Cues id={seen[key]} and id={cue.id} in production id={cue.production_id} "
                f"both become number {value}. Renumber one before migrating."
            )
        seen[key] = cue.id
        Cue.objects.filter(pk=cue.pk).update(number_decimal=value)

    # Free-text run labels -> Run rows. Queryset .update() is used on events
    # because the historical model has no append-only guard, and this is a
    # one-off schema move rather than an edit of the log.
    groups = (
        CueEvent.objects.values("cue__production_id", "run_label")
        .annotate(first=Min("fired_at"))
        .order_by("first")
    )
    for group in groups:
        run = Run.objects.create(production_id=group["cue__production_id"], label=group["run_label"])
        Run.objects.filter(pk=run.pk).update(created_at=group["first"])
        CueEvent.objects.filter(
            cue__production_id=group["cue__production_id"], run_label=group["run_label"]
        ).update(run=run)

    for event in CueEvent.objects.select_related("cue"):
        CueEvent.objects.filter(pk=event.pk).update(
            action="go",
            cue_number=event.cue.number_decimal,
            cue_label=event.cue.label,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("shows", "0002_runs_snapshots_decimal_numbers"),
    ]

    # No reverse: the old free-text run_label and char numbers can't be
    # reconstructed losslessly once the new columns are the source of truth.
    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
