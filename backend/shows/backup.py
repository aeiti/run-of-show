"""Whole-production backup: one JSON file with the details, cues, runs and
run logs, and the import that turns such a file back into a new production.

Duplicating a production is an export without runs, imported straight back.

Timestamps are kept as they were: a run's ``created_at``, an event's
``fired_at`` and a cue note's times are set automatically on insert, so they
are written after it. That is the one time event rows are touched after they are created,
and only to restore the original history.
"""

from django.db import transaction
from django.utils import timezone

from . import services
from .models import Cue, CueEvent, CueNote, Production, Run
from .serializers import (
    BACKUP_FORMAT,
    BACKUP_VERSION,
    BackupCueSerializer,
    BackupProductionSerializer,
    BackupRunSerializer,
    BackupSerializer,
)

def export_production(production, runs=True):
    data = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": timezone.now().isoformat(),
        "production": BackupProductionSerializer(production).data,
        "cues": BackupCueSerializer(production.cues.all(), many=True).data,
    }
    if runs:
        history = production.runs.order_by("created_at", "id").prefetch_related("events__cue", "cue_notes__cue")
        data["runs"] = BackupRunSerializer(history, many=True).data
    return data


def validate(data):
    """Validated data for ``import_production``; raises DRF's ValidationError."""
    serializer = BackupSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


@transaction.atomic
def import_production(owner, data, **details):
    """Create a new production from validated backup data. ``details`` override its fields."""
    production = Production.objects.create(owner=owner, **{**data["production"], **details})
    Cue.objects.bulk_create(Cue(production=production, **cue) for cue in data.get("cues", []))
    cue_ids = dict(production.cues.values_list("number", "id"))

    for run_data in data.get("runs", []):
        run_data = dict(run_data)
        created_at = run_data.pop("created_at")
        events = run_data.pop("events", [])
        notes = run_data.pop("cue_notes", [])
        if "started_at" not in run_data:
            # A version 1 file has no start; as in migration 0010, it was the first GO.
            run_data["started_at"] = first_start(events, run_data.get("ended_at"))
        run = Run.objects.create(production=production, **run_data)
        Run.objects.filter(pk=run.pk).update(created_at=created_at)

        rows = []
        for event in events:
            event = dict(event)
            linked = (event.pop("cue", None) or {}).get("number")
            rows.append(CueEvent(run=run, cue_id=cue_ids.get(linked), **event))
        fired = [row.fired_at for row in rows]
        CueEvent.objects.bulk_create(rows)
        for row, fired_at in zip(rows, fired):
            row.fired_at = fired_at
        CueEvent.objects.bulk_update(rows, ["fired_at"])

        for note in notes:
            note = dict(note)
            linked = (note.pop("cue", None) or {}).get("number")
            created_at = note.pop("created_at")
            updated_at = note.pop("updated_at", None) or created_at
            row = CueNote.objects.create(run=run, cue_id=cue_ids.get(linked), **note)
            CueNote.objects.filter(pk=row.pk).update(created_at=created_at, updated_at=updated_at)

    return production


def first_start(events, ended_at):
    starts = sorted(e["fired_at"] for e in events if e["action"] in services.STARTS)
    if starts and (ended_at is None or starts[0] <= ended_at):
        return starts[0]
    return None


def duplicate(production, owner, **details):
    data = validate(export_production(production, runs=False))
    details.setdefault("name", f"{production.name} (copy)"[:200])
    return import_production(owner, data, **details)
