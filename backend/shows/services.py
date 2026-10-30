"""Run state and operator actions.

The active cue is whatever the last event made active (none after a reset).
"Next" and "previous" are found by cue number using the number snapshotted on
that event, so they still work if the active cue was renumbered or deleted.

A HOLD pauses the run with a reason until a RESUME. Both are logged with the
cue that was active, but neither moves it, and no cue action is accepted while
the run is held. Ending a held run is allowed; the hold then lasts until the end.

The first GO or GOTO records when the run started (``Run.started_at``), unless
an operator has already set it. A hold, a reset or a step back doesn't: none
of them fires a cue, and a hold before the top of the show is a late start.
"""

from django.db import transaction
from django.utils import timezone

from .models import Cue, CueEvent, Run


class RunActionError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# The actions that move the active cue. Holds and resumes only record it.
CUE_ACTIONS = [CueEvent.Action.GO, CueEvent.Action.BACK, CueEvent.Action.GOTO, CueEvent.Action.RESET]
HOLD_ACTIONS = [CueEvent.Action.HOLD, CueEvent.Action.RESUME]
# The actions that fire a cue, so the first of them starts the run.
STARTS = [CueEvent.Action.GO, CueEvent.Action.GOTO]


def active_number(run):
    # A reset event records no cue number, so it clears the active cue too.
    last = run.events.filter(action__in=CUE_ACTIONS).order_by("-fired_at", "-id").first()
    return last.cue_number if last else None


def current_hold(run):
    """The hold event the run is paused on, or None."""
    last = run.events.filter(action__in=HOLD_ACTIONS).order_by("-fired_at", "-id").first()
    return last if last and last.action == CueEvent.Action.HOLD else None


def run_state(run):
    cues = Cue.objects.filter(production=run.production_id)
    number = active_number(run)
    if number is None:
        active, following = None, cues.first()
    else:
        active = cues.filter(number=number).first()
        following = cues.filter(number__gt=number).first()
    hold = current_hold(run)
    return {
        "active_cue": active.id if active else None,
        "active_number": number,
        "next_cue": following.id if following else None,
        "hold": {"since": hold.fired_at, "reason": hold.note} if hold else None,
    }


def _record(run, action, cue):
    event = CueEvent.objects.create(
        run=run,
        action=action,
        cue=cue,
        cue_number=cue.number if cue else None,
        cue_label=cue.label if cue else "",
    )
    if action in STARTS and run.started_at is None:
        run.started_at = event.fired_at
        run.save(update_fields=["started_at"])
    return event


def _locked(run, held_ok=False):
    # Serialise actions on one run so two GOs can't both fire the same "next" cue.
    run = Run.objects.select_for_update().get(pk=run.pk)
    if run.ended_at is not None:
        raise RunActionError("This run has ended.", status=409)
    if not held_ok and current_hold(run):
        raise RunActionError("The run is on hold. Resume it first.", status=409)
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


def _record_hold(run, action, note=""):
    # Copies the active cue from the last cue action, so a hold during a cue
    # that has since been deleted still says which cue it was.
    last = run.events.filter(action__in=CUE_ACTIONS).order_by("-fired_at", "-id").first()
    return CueEvent.objects.create(
        run=run,
        action=action,
        cue=last.cue if last else None,
        cue_number=last.cue_number if last else None,
        cue_label=last.cue_label if last else "",
        note=note,
    )


@transaction.atomic
def hold(run, reason):
    run = _locked(run, held_ok=True)
    if current_hold(run):
        raise RunActionError("The run is already on hold.", status=409)
    return _record_hold(run, CueEvent.Action.HOLD, reason)


@transaction.atomic
def resume(run):
    run = _locked(run, held_ok=True)
    if not current_hold(run):
        raise RunActionError("The run is not on hold.", status=409)
    return _record_hold(run, CueEvent.Action.RESUME)


def end(run):
    if run.ended_at is None:
        run.ended_at = timezone.now()
        run.save(update_fields=["ended_at"])
    return run
