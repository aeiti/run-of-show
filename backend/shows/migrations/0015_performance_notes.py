import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def stamp_existing(apps, schema_editor):
    # Every note so far was written on the board, at the moment it was made.
    CueNote = apps.get_model("shows", "CueNote")
    CueNote.objects.filter(at__isnull=True).update(at=models.F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("shows", "0014_console_events"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="cuenote",
            name="at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cuenote",
            name="added_later",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name="cuenote",
            name="follow_up",
            field=models.TextField(blank=True, db_default="", default="", max_length=4000),
        ),
        migrations.AddField(
            model_name="cuenote",
            name="follow_up_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="cuenote",
            name="follow_up_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(stamp_existing, migrations.RunPython.noop),
    ]
