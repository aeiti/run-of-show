"""Run state and operator actions.

The active cue is whatever the last event made active (none after a reset).
"Next" and "previous" are found by cue number using the number snapshotted on
that event, so they still work if the active cue was renumbered or deleted.
"""

from django.db import transaction
from django.utils import timezone

from .models import Cue, CueEvent, Run


class RunActionError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def active_number(run):
    # A reset event records no cue number, so it clears the active cue too.
    last = run.events.order_by("-fired_at", "-id").first()
    return last.cue_number if last else None


def run_state(run):
    cues = Cue.objects.filter(production=run.production_id)
    number = active_number(run)
    if number is None:
        active, following = None, cues.first()
    else:
        active = cues.filter(number=number).first()
        following = cues.filter(number__gt=number).first()
    return {
        "active_cue": active.id if active else None,
        "active_number": number,
        "next_cue": following.id if following else None,
    }


def _record(run, action, cue):
    return CueEvent.objects.create(
        run=run,
        action=action,
        cue=cue,
        cue_number=cue.number if cue else None,
        cue_label=cue.label if cue else "",
    )


def _locked(run):
    # Serialise actions on one run so two GOs can't both fire the same "next" cue.
    run = Run.objects.select_for_update().get(pk=run.pk)
    if run.ended_at is not None:
        raise RunActionError("This run has ended.", status=409)
    return run


def _own_cue(run, cue_id):
    cue = Cue.objects.filter(production=run.production_id, pk=cue_id).first()
    if cue is None:
        raise RunActionError("That cue is not in this production.")
    return cue


@transaction.atomic
def go(run, cue_id=None):
    """Fire the loaded cue if one is given, otherwise the cue after the active one."""
    run = _locked(run)
    if cue_id is not None:
        return _record(run, CueEvent.Action.GO, _own_cue(run, cue_id))
    cues = Cue.objects.filter(production=run.production_id)
    number = active_number(run)
    cue = cues.first() if number is None else cues.filter(number__gt=number).first()
    if cue is None:
        raise RunActionError("End of the cue list.")
    return _record(run, CueEvent.Action.GO, cue)


@transaction.atomic
def back(run):
    run = _locked(run)
    number = active_number(run)
    if number is None:
        raise RunActionError("No cue is active.")
    cue = Cue.objects.filter(production=run.production_id, number__lt=number).last()
    if cue is None:
        raise RunActionError("Already at the first cue.")
    return _record(run, CueEvent.Action.BACK, cue)


@transaction.atomic
def goto(run, cue_id):
    run = _locked(run)
    return _record(run, CueEvent.Action.GOTO, _own_cue(run, cue_id))


@transaction.atomic
def reset(run):
    run = _locked(run)
    return _record(run, CueEvent.Action.RESET, None)


def end(run):
    if run.ended_at is None:
        run.ended_at = timezone.now()
        run.save(update_fields=["ended_at"])
    return run
