"""Following an ETC Eos console's cue fires over OSC. The app only listens.

Eos sends ``/eos/out/event/cue/<cue list>/<cue number>/<action>`` with the cue's
label as its argument, where the action is fire, stop or resume, every time a
cue is fired, stopped or resumed (Eos online help, OSC Show Control and OSC
Dictionary > OSC Outputs). Over UDP it sends them to the OSC TX IP address and
port set on the console; over TCP to whoever has connected to its OSC port,
framed by a length header (OSC 1.0, the console's default) or SLIP (OSC 1.1).

This module parses those bytes and records what each fire means on the
production's open run, telling open boards just as a GO from a board does.
``console.py`` does the networking, inside the server process.
"""

import re
import struct
import time
from decimal import Decimal, InvalidOperation

from . import live, services
from .models import ConsoleEvent, Cue, Run
from .serializers import CueEventSerializer, RunStateSerializer

CUE_EVENT = re.compile(r"^/eos/out/event/cue/(?P<list>\d+)/(?P<number>[0-9.]+)/(?P<action>fire|stop|resume)$", re.I)

# A repeat of the same cue within this many seconds is the same fire arriving twice
# (both UDP and TCP set up, or Eos sending its standard and custom cue events).
REPEAT_WINDOW = 1.0


class OSCError(ValueError):
    pass


def _string(data, at):
    end = data.find(b"\0", at)
    if end < 0:
        raise OSCError("Unterminated string.")
    # Strings are padded with nulls to a multiple of four bytes.
    return data[at:end].decode("utf-8", "replace"), (end + 4) & ~3


def _message(data):
    address, at = _string(data, 0)
    if at >= len(data) or data[at : at + 1] != b",":
        return address, []  # no type tags: an old-style message with no arguments we can read
    tags, at = _string(data, at)
    args = []
    for tag in tags[1:]:
        if tag == "i":
            args.append(struct.unpack_from(">i", data, at)[0])
            at += 4
        elif tag == "f":
            args.append(struct.unpack_from(">f", data, at)[0])
            at += 4
        elif tag == "s":
            value, at = _string(data, at)
            args.append(value)
        elif tag == "h":
            args.append(struct.unpack_from(">q", data, at)[0])
            at += 8
        elif tag == "d":
            args.append(struct.unpack_from(">d", data, at)[0])
            at += 8
        elif tag == "b":
            size = struct.unpack_from(">i", data, at)[0]
            args.append(data[at + 4 : at + 4 + size])
            at = (at + 4 + size + 3) & ~3
        elif tag in "TFNI":
            args.append({"T": True, "F": False, "N": None, "I": float("inf")}[tag])
        else:
            break  # a type we don't know the size of; the address is what matters
    return address, args


def parse_packet(data):
    """Every (address, args) in an OSC packet, unpacking bundles."""
    try:
        if data.startswith(b"#bundle\0"):
            messages, at = [], 16  # "#bundle\0" and an 8-byte time tag
            while at + 4 <= len(data):
                size = struct.unpack_from(">i", data, at)[0]
                messages += parse_packet(data[at + 4 : at + 4 + size])
                at += 4 + size
            return messages
        return [_message(data)]
    except (struct.error, OSCError):
        raise OSCError("Not an OSC packet.") from None


class LengthFramer:
    """OSC 1.0 over TCP: each packet follows its length as a 32-bit big-endian integer."""

    def __init__(self):
        self.buffer = b""

    def feed(self, chunk):
        self.buffer += chunk
        packets = []
        while len(self.buffer) >= 4:
            size = struct.unpack_from(">I", self.buffer)[0]
            if len(self.buffer) < 4 + size:
                break
            packets.append(self.buffer[4 : 4 + size])
            self.buffer = self.buffer[4 + size :]
        return packets


class SlipFramer:
    """OSC 1.1 over TCP: packets end with SLIP END (0xC0), with END and ESC escaped inside."""

    END, ESC, ESC_END, ESC_ESC = 0xC0, 0xDB, 0xDC, 0xDD

    def __init__(self):
        self.buffer = b""

    def feed(self, chunk):
        self.buffer += chunk
        *frames, self.buffer = self.buffer.split(bytes([self.END]))
        return [self._unescape(f) for f in frames if f]

    def _unescape(self, frame):
        return frame.replace(bytes([self.ESC, self.ESC_END]), bytes([self.END])).replace(
            bytes([self.ESC, self.ESC_ESC]), bytes([self.ESC])
        )


def cue_fire(address):
    """``(cue list, cue number)`` for a cue fire event, otherwise None."""
    match = CUE_EVENT.match(address)
    if not match or match["action"].lower() != "fire":
        return None
    try:
        return int(match["list"]), Decimal(match["number"])
    except InvalidOperation:
        return None


class Skip(Exception):
    """A fire that won't be recorded, and why."""


def open_run(production):
    run = Run.objects.filter(production=production, ended_at__isnull=True).order_by("-created_at", "-id").first()
    if run is None:
        raise Skip("No run is open. Start one on the board.")
    return run


def plan(production, number):
    """The run, action ("go" or "goto") and cue for a fire of cue ``number``.

    Going forward is a GO of that cue, which also covers a skip ahead. A fire
    behind the active cue is the console going back (Eos fires the cue it goes
    back to), recorded as a GOTO since it may be more than one cue back.
    """
    run = open_run(production)
    cue = Cue.objects.filter(production=production, number=number).first()
    if cue is None:
        raise Skip(f"Q{number.normalize():f} isn't in this production's cue list.")
    active = services.active_number(run)
    action = "goto" if active is not None and number <= active else "go"
    return run, action, cue


def _cue(number):
    return f"Q{Decimal(number).normalize():f}"


def describe(address, args):
    """A line for the run log about an Eos show control event, or None for anything else.

    These are the ``/eos/out/event/...`` messages Eos sends as it acts (Eos
    online help, OSC Show Control and OSC Dictionary > OSC Outputs).
    """
    parts = address.strip("/").split("/")
    if [p.lower() for p in parts[:3]] != ["eos", "out", "event"]:
        return None
    what = [p.lower() for p in parts[3:]]
    first = args[0] if args else None
    try:
        if len(what) == 4 and what[0] == "cue":
            label = f" {first}" if isinstance(first, str) and first else ""
            action = {"fire": "fired", "stop": "stopped", "resume": "resumed"}.get(what[3], what[3])
            return f"Eos {action} list {what[1]} {_cue(what[2])}{label}"
        if len(what) == 2 and what[0] == "macro":
            return f"Eos ran macro {what[1]}"
        if len(what) == 2 and what[0] == "sub":
            state = {1: " bump on", 0: " bump off"}.get(first, "")
            return f"Eos submaster {what[1]}{state}"
        if len(what) == 3 and what[0] == "relay":
            # The dictionary documents 0 as on and 1 as off.
            state = {0: " on", 1: " off"}.get(first, "")
            return f"Eos relay {what[1]} group {what[2]}{state}"
        if len(what) == 2 and what[0] == "show":
            path = f": {first}" if isinstance(first, str) and first else ""
            return f"Eos show {what[1]}{path}"
    except InvalidOperation:
        pass
    return f"Eos {address}" + (f" {' '.join(map(str, args))}" if args else "")


def log_console_event(production_id, kind, text, address=""):
    """Add a line to the open run's log and tell its boards. Nothing if no run is open."""
    run = Run.objects.filter(production=production_id, ended_at__isnull=True).order_by("-created_at", "-id").first()
    if run is None:
        return None
    event = ConsoleEvent.objects.create(run=run, kind=kind, text=text[:500], address=address[:300])
    live.broadcast(production_id, {"type": "console.log", "run": run.id})
    return event


class Repeats:
    """Recognises the same event arriving again within ``REPEAT_WINDOW``."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last = None  # (address, when)

    def seen(self, address):
        now = self.clock()
        repeat = self.last is not None and self.last[0] == address.lower() and now - self.last[1] < REPEAT_WINDOW
        self.last = (address.lower(), now)
        return repeat


class Relay:
    """Records the cue fires in OSC packets from the console on the production's open run.

    ``log(text, problem)`` reports each fire recorded, or skipped (``problem`` true). Runs synchronously,
    with database access; the caller keeps packets in order.
    """

    def __init__(self, production_id, cue_list, log, clock=time.monotonic):
        self.production_id = production_id
        self.cue_list = cue_list
        self.log = log
        self.repeats = Repeats(clock)

    def handle(self, data):
        """Record any cue fires in ``data``, and log its other show control events. False if it wasn't OSC."""
        try:
            messages = parse_packet(data)
        except OSCError:
            return False
        for address, args in messages:
            text = describe(address, args)
            if text is None or self.repeats.seen(address):
                continue
            fire = cue_fire(address)
            if fire is not None and fire[0] == self.cue_list:
                self.record(fire[1], address)
            else:
                log_console_event(self.production_id, ConsoleEvent.Kind.SHOW_CONTROL, text, address)
        return True

    def record(self, number, address=""):
        name = f"Q{number.normalize():f}"
        try:
            run, action, cue = plan(self.production_id, number)
            event = (services.go if action == "go" else services.goto)(run, cue.id, source="console")
        except (Skip, services.RunActionError) as e:
            text = f"Console fired {name}; not recorded. {e}"
            self.log(text, True)
            log_console_event(self.production_id, ConsoleEvent.Kind.SHOW_CONTROL, text, address)
            return
        # The same message the API sends for a GO from a board (see RunViewSet.live_message).
        live.broadcast(
            self.production_id,
            {
                "type": "run.event",
                "run": run.id,
                "event": CueEventSerializer(event).data,
                "state": RunStateSerializer(services.run_state(run)).data,
            },
        )
        self.log(f"Console fired {name}: {action.upper()} {name} {cue.label}".rstrip(), False)
