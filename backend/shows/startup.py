"""Start the Eos console listeners when the server starts, not on its first request.

The listeners (``console.py``) live on the server's event loop, and Daphne,
which ``runserver`` serves with, has no startup hook: they start with the
first request or socket the server handles. If the backend restarted mid-show
with no board open, the console's cues would go unrecorded until someone
opened one.

So the process that serves asks itself for a page as soon as its port
answers. That request starts the listeners like any other. ``runserver``
restarts this process on every code change, and the new one wakes itself
the same way.
"""

import logging
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8000


def serving_port(argv, environ):
    """The port this process serves on, if it is the one ``runserver`` serves from; else None.

    With the autoreloader, ``runserver`` runs twice: a watcher, and a child
    (``RUN_MAIN=true``) that serves. Without it (``--noreload``) the one
    process serves. Any other command (migrate, shell, pytest) serves nothing.
    """
    if "runserver" not in argv[1:2]:
        return None
    args = argv[2:]
    if environ.get("RUN_MAIN") != "true" and "--noreload" not in args:
        return None
    addrport = next((arg for arg in args if not arg.startswith("-")), "")
    port = addrport.rsplit(":", 1)[-1]
    return int(port) if port.isdigit() else DEFAULT_PORT


def wake(port, timeout=60.0, interval=0.5):
    """Request a page from the server on ``port`` until it answers, or ``timeout`` runs out.

    Any HTTP answer will do, a 401 or 404 included: the request has reached
    the server, which starts the listeners. Returns whether it answered.
    """
    url = f"http://127.0.0.1:{port}/api/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=5).close()
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            time.sleep(interval)
    logger.warning("Eos console listeners: the server on port %s didn't answer, so they start on its first request", port)
    return False


def wake_in_background(port):
    threading.Thread(target=wake, args=(port,), name="eos-listeners-wake", daemon=True).start()
