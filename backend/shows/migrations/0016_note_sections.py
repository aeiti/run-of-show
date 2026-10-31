from django.db import migrations, models


def fold_run_notes(apps, schema_editor):
    # Each run's free-text notes become a note in the Show section, as one written up after the run.
    Run = apps.get_model("shows", "Run")
    CueNote = apps.get_model("shows", "CueNote")
    for run in Run.objects.exclude(notes=""):
        if run.notes.strip():
            CueNote.objects.create(run=run, text=run.notes.strip(), added_later=True, section="Show")
    Run.objects.exclude(notes="").update(notes="")


class Migration(migrations.Migration):

    dependencies = [
        ("shows", "0015_performance_notes"),
    ]

    operations = [
        migrations.AddField(
            model_name="production",
            name="note_sections",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cuenote",
            name="section",
            field=models.CharField(blank=True, db_default="", default="", max_length=100),
        ),
        migrations.AddField(
            model_name="cuenote",
            name="show_cue",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AlterField(
            model_name="run",
            name="notes",
            field=models.TextField(blank=True, db_default=""),
        ),
        migrations.RunPython(fold_run_notes, migrations.RunPython.noop),
    ]
