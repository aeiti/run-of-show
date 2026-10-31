"""Real-time updates: tell every open board on a production what just changed.

Each production has a channel group, and every open board joins the group of
the production it shows (see ``consumers.py``). After a write commits, the API
sends the group one small message:

* ``run.event``: an operator action, with the event and the run's new state,
  so boards can play it straight away.
* ``cues``, ``runs``, ``notes``, ``files``, ``production``: that part changed;
  boards refetch it. A new or removed logo is a ``production`` change.
* ``access``: membership changed. Each socket rechecks its user's access and
  closes if it's gone; boards refetch the production, since the role may differ.
* ``production.deleted``: boards leave.
* ``console.log``: a console or network line was added to a run's log;
  boards showing that run refetch it.
* ``cue.progress``: how far the active cue's fade has got on the console;
  ``cue.stop`` and ``cue.resume``: the console stopped or resumed it (see
  ``eos.py``). Boards move the cue's fade bar; nothing is recorded.
* ``console``: the Eos console listener's status changed (see ``console.py``),
  sent with the new status.

Each user also has a group, used to close their sockets when their sign-in
ends (sign-out, a password change or reset, suspension, deletion).

The channel layer is in-memory by default, which only reaches sockets served
by the same process (fine for ``runserver``). Several processes need a shared
layer such as Redis; see ``CHANNEL_LAYERS`` in settings.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


def production_group(production_id):
    return f"production-{production_id}"


def user_group(user_id):
    return f"user-{user_id}"


def _send(group, message):
    layer = get_channel_layer()
    if layer is not None:
        # After commit, so a board that refetches sees the change.
        transaction.on_commit(lambda: async_to_sync(layer.group_send)(group, message))


def broadcast(production_id, message):
    _send(production_group(production_id), {"type": "production.message", "message": message})


async def broadcast_now(production_id, message):
    """``broadcast`` from async code with nothing to commit, such as a console listener's status."""
    layer = get_channel_layer()
    if layer is not None:
        await layer.group_send(production_group(production_id), {"type": "production.message", "message": message})


def end_sessions(user_id):
    _send(user_group(user_id), {"type": "session.ended"})
