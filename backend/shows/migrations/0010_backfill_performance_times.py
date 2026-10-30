from django.db import migrations, models

# The actions that start a run: the ones that fire a cue (as services.STARTS).
STARTS = ["go", "goto"]


def forwards(apps, schema_editor):
    Production = apps.get_model("shows", "Production")
    Run = apps.get_model("shows", "Run")
    CueEvent = apps.get_model("shows", "CueEvent")

    # The old single date was the date the show was on: its opening.
    Production.objects.filter(performance_date__isnull=False).update(opening_date=models.F("performance_date"))

    # Runs from before started_at existed started at their first GO or GOTO,
    # unless that would put the start after the end (a hand-edited log).
    first = (
        CueEvent.objects.filter(run=models.OuterRef("pk"), action__in=STARTS)
        .order_by("fired_at", "id")
        .values("fired_at")[:1]
    )
    for run in Run.objects.filter(started_at__isnull=True).annotate(first=models.Subquery(first)):
        if run.first is not None and (run.ended_at is None or run.first <= run.ended_at):
            Run.objects.filter(pk=run.pk).update(started_at=run.first)


def backwards(apps, schema_editor):
    Production = apps.get_model("shows", "Production")
    Production.objects.update(performance_date=models.F("opening_date"))


class Migration(migrations.Migration):
    dependencies = [
        ("shows", "0009_performance_times"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name="production",
            name="performance_date",
        ),
        migrations.AddConstraint(
            model_name="production",
            constraint=models.CheckConstraint(
                condition=models.Q(closing_date__isnull=True)
                | models.Q(opening_date__isnull=True)
                | models.Q(closing_date__gte=models.F("opening_date")),
                name="closing_not_before_opening",
            ),
        ),
        migrations.AddConstraint(
            model_name="run",
            constraint=models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(started_at__isnull=True)
                | models.Q(ended_at__gte=models.F("started_at")),
                name="run_ends_after_start",
            ),
        ),
    ]
