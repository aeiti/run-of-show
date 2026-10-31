"""Listening to Eos consoles from inside the server process.

A production whose Eos console settings are enabled gets a listener: a UDP
socket the console sends to, or a TCP connection to the console that is only
read from. Each cue the console fires is recorded on the production's open run
(``eos.Relay``). Nothing is ever sent to a console.

This runs in the server process because the channel layer is in memory: only
this process can reach the boards' sockets, and so only it can tell them about
a cue straight away. Daphne has no startup hook, so the listeners start on the
first request or socket the server handles, which an open board makes within
seconds of a restart. Saving a production's settings restarts its listener.

Each listener keeps a status that boards show next to "Synced": off, listening,
connecting, connected or a problem, when the console was last heard from, and
the last fire it couldn't record. A change is sent to the production's boards
as a ``console`` message.
"""

import asyncio
import logging
import re
from collections import deque
from datetime import datetime, timezone

from channels.db import database_sync_to_async
from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save

from . import live
from .eos import LengthFramer, OSCError, Relay, SlipFramer, log_console_event, parse_packet
from .models import ConsoleEvent, EosConsole

log = logging.getLogger(__name__)

FRAMERS = {"1.0": LengthFramer, "1.1": SlipFramer}
# Hearing from the console after this long a silence is news worth sending to boards.
HEARD_AGAIN_AFTER = 10
# How many received messages, and what came of them, each production keeps to show.
RECENT = 50
# Fade progress, sent many times a second while a cue runs: kept in the recent
# list but not written to the server log.
PROGRESS = re.compile(r"^/eos/out/active/cue(/text|/\d+/[0-9.]+)?$", re.I)


def plain(arg):
    """An OSC argument as something JSON can carry."""
    if isinstance(arg, bytes):
        return f"<{len(arg)} bytes>"
    if isinstance(arg, float) and arg in (float("inf"), float("-inf")):
        return str(arg)
    return arg


def now():
    return datetime.now(timezone.utc)


def describe(config):
    if config.transport == EosConsole.Transport.UDP:
        return f"UDP port {config.port}"
    return f"{config.host}:{config.port} (TCP)"


class Listener:
    def __init__(self, config, supervisor):
        self.config = config
        self.production_id = config.production_id
        self.supervisor = supervisor
        self.relay = Relay(self.production_id, config.cue_list, self.note)
        self.packets = asyncio.Queue()
        self.transport = None
        self.tasks = []
        self.heard = None
        self.logged = None  # the last line this listener put in the run log

    async def start(self):
        self.tasks.append(asyncio.create_task(self.work()))
        if self.config.transport == EosConsole.Transport.UDP:
            loop = asyncio.get_running_loop()
            try:
                self.transport, _ = await loop.create_datagram_endpoint(
                    lambda: Datagrams(self), local_addr=(settings.EOS_BIND_ADDRESS, self.config.port)
                )
            except OSError as e:
                self.set(state="error", detail=f"Can't listen on UDP port {self.config.port}: {e.strerror or e}")
                return
            self.set(state="listening", detail=f"Listening on {describe(self.config)}")
        else:
            self.tasks.append(asyncio.create_task(self.read_tcp()))

    async def stop(self):
        if self.transport is not None:
            self.transport.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def set(self, **changes):
        before = self.supervisor.status(self.production_id)
        self.supervisor.update(self.production_id, **changes)
        if "state" in changes:
            self.log_network(before, self.supervisor.status(self.production_id))

    def log_network(self, before, after):
        """Put the connection's ups and downs in the run log, once each."""
        text = None
        if after["state"] in ("listening", "connected", "error"):
            text = after["detail"]
        elif after["state"] == "connecting" and before["state"] == "connected":
            text = f"Lost the connection to {describe(self.config)}"
        if text and text != self.logged:
            self.logged = text
            self.supervisor.log(self.production_id, text)

    def note(self, text, problem):
        """From the relay, in the database thread."""
        log.info("Production %s: %s", self.production_id, text)
        when = now().isoformat()
        self.supervisor.loop.call_soon_threadsafe(
            lambda: self.supervisor.remember(self.production_id, {"at": when, "result": text, "problem": problem})
        )
        if problem:
            self.supervisor.loop.call_soon_threadsafe(lambda: self.set(problem=text, problem_at=when))

    def received(self, data, source=None):
        when = now()
        self.record_received(data, source, when)
        if self.heard is None or (when - self.heard).total_seconds() > HEARD_AGAIN_AFTER:
            self.set(heard=when.isoformat())
        else:
            self.supervisor.quietly(self.production_id, heard=when.isoformat())
        self.heard = when
        self.packets.put_nowait(data)

    def record_received(self, data, source, when):
        """Keep each message to show, and log it, before the relay acts on it."""
        frm = f" from {source}" if source else ""
        try:
            messages = parse_packet(data)
        except OSCError:
            log.info("Production %s: %s bytes%s, not OSC", self.production_id, len(data), frm)
            self.supervisor.remember(self.production_id, {"at": when.isoformat(), "address": None, "args": [], "note": f"{len(data)} bytes{frm}, not OSC"})
            return
        for address, args in messages:
            args = [plain(a) for a in args]
            if not PROGRESS.match(address):
                log.info("Production %s: OSC%s %s %s", self.production_id, frm, address, args)
            self.supervisor.remember(self.production_id, {"at": when.isoformat(), "address": address, "args": args})

    async def work(self):
        # One packet at a time, in order, each in the database thread.
        handle = database_sync_to_async(self.relay.handle)
        while True:
            await handle(await self.packets.get())

    async def read_tcp(self):
        host, port = self.config.host, self.config.port
        delay = 1
        while True:
            self.set(state="connecting", detail=f"Connecting to {describe(self.config)}")
            try:
                reader, writer = await asyncio.open_connection(host, port)
            except OSError as e:
                self.set(state="error", detail=f"Can't connect to {host}:{port}: {e.strerror or e}. Trying again.")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            self.set(state="connected", detail=f"Connected to {describe(self.config)}")
            delay = 1
            framer = FRAMERS[self.config.framing]()
            try:
                while chunk := await reader.read(65536):
                    for packet in framer.feed(chunk):
                        self.received(packet, host)
            except OSError:
                pass
            finally:
                writer.close()


class Datagrams(asyncio.DatagramProtocol):
    def __init__(self, listener):
        self.listener = listener

    def datagram_received(self, data, addr):
        self.listener.received(data, addr[0])


class Supervisor:
    """Keeps one listener per enabled production, on the server's event loop."""

    def __init__(self):
        self.loop = None
        self.listeners = {}
        self.statuses = {}
        self.recents = {}
        self.lock = None
        self.starting = None

    def ensure_started(self):
        """Called on the server's loop for each request; starts everything the first time."""
        if self.loop is not None:
            return
        self.loop = asyncio.get_running_loop()
        self.lock = asyncio.Lock()
        self.starting = self.loop.create_task(self.start_all())

    async def start_all(self):
        ids = await database_sync_to_async(
            lambda: list(EosConsole.objects.filter(enabled=True).values_list("production_id", flat=True))
        )()
        for production_id in ids:
            await self.apply(production_id)

    def changed(self, production_id):
        """A production's settings changed (from any thread, after commit)."""
        if self.loop is not None:
            self.loop.call_soon_threadsafe(lambda: self.loop.create_task(self.apply(production_id)))

    async def apply(self, production_id):
        async with self.lock:
            old = self.listeners.pop(production_id, None)
            if old is not None:
                await old.stop()
            config = await database_sync_to_async(lambda: EosConsole.objects.filter(pk=production_id).first())()
            if old is not None and (config is None or not config.enabled):
                self.log(production_id, "Stopped following the console")
            if config is None or not config.enabled:
                self.statuses.pop(production_id, None)
                self.recents.pop(production_id, None)
                self.send(production_id)
                return
            self.recents[production_id] = deque(maxlen=RECENT)
            self.statuses[production_id] = {"state": "starting", "detail": "", "heard": None, "problem": "", "problem_at": None}
            listener = Listener(config, self)
            self.listeners[production_id] = listener
            await listener.start()

    async def stop_all(self):
        for production_id in list(self.listeners):
            await self.listeners.pop(production_id).stop()

    def status(self, production_id):
        return self.statuses.get(production_id, {"state": "off", "detail": "", "heard": None, "problem": "", "problem_at": None})

    def log(self, production_id, text):
        """A network line in the open run's log, from the event loop."""
        self.loop.create_task(
            database_sync_to_async(log_console_event)(production_id, ConsoleEvent.Kind.NETWORK, text)
        )

    def remember(self, production_id, entry):
        if production_id in self.recents:
            self.recents[production_id].append(entry)

    def recent(self, production_id):
        """What the listener received and recorded, newest first."""
        return list(reversed(self.recents.get(production_id, ())))

    def quietly(self, production_id, **changes):
        if production_id in self.statuses:
            self.statuses[production_id] = {**self.statuses[production_id], **changes}

    def update(self, production_id, **changes):
        if production_id in self.statuses:
            self.quietly(production_id, **changes)
            self.send(production_id)

    def send(self, production_id):
        self.loop.create_task(live.broadcast_now(production_id, {"type": "console", "status": self.status(production_id)}))


supervisor = Supervisor()


def settings_changed(sender, instance, **kwargs):
    production_id = instance.production_id
    transaction.on_commit(lambda: supervisor.changed(production_id))


post_save.connect(settings_changed, sender=EosConsole)
post_delete.connect(settings_changed, sender=EosConsole)
