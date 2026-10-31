"""Following an ETC Eos console's cue fires over OSC. The app only listens.

Eos sends ``/eos/out/event/cue/<cue list>/<cue number>/<action>`` with the cue's
label as its argument, where the action is fire, stop or resume, every time a
cue is fired, stopped or resumed (Eos online help, OSC Show Control and OSC
Dictionary > OSC Outputs). Over UDP it sends them to the OSC TX IP address and
port set on the console; over TCP to whoever has connected to its OSC port,
framed by a length header (OSC 1.0, the console's default) or SLIP (OSC 1.1).

This module parses those bytes and decides what each fire means for the
production's open run. ``listen_eos`` does the networking, and records the
cue through the app's API so every open board updates as if an operator had
pressed GO.
"""

import re
import struct
import time
from decimal import Decimal, InvalidOperation

from .models import Cue, Run
from .services import active_number

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
    active = active_number(run)
    action = "goto" if active is not None and number <= active else "go"
    return run, action, cue


class Repeats:
    """Recognises the same fire arriving again within ``REPEAT_WINDOW``."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last = None  # (cue list, number, when)

    def seen(self, cue_list, number):
        now = self.clock()
        repeat = self.last is not None and self.last[:2] == (cue_list, number) and now - self.last[2] < REPEAT_WINDOW
        self.last = (cue_list, number, now)
        return repeat


class Relay:
    """Turns OSC packets from the console into GO and GOTO requests on the open run.

    ``post(path, body)`` sends one request to the app's API as the console's
    account and returns ``(status, data)``; ``log(text)`` reports what happened.
    """

    def __init__(self, production, cue_list, post, log, clock=time.monotonic):
        self.production = production
        self.cue_list = cue_list
        self.post = post
        self.log = log
        self.repeats = Repeats(clock)

    def handle(self, data):
        try:
            messages = parse_packet(data)
        except OSCError as e:
            self.log(f"Ignored {len(data)} bytes: {e}")
            return
        for address, _args in messages:
            fire = cue_fire(address)
            if fire is None or fire[0] != self.cue_list:
                continue
            if self.repeats.seen(*fire):
                continue
            self.record(fire[1])

    def record(self, number):
        name = f"Q{number.normalize():f}"
        try:
            run, action, cue = plan(self.production, number)
        except Skip as e:
            self.log(f"Console fired {name}; not recorded. {e}")
            return
        status, data = self.post(f"runs/{run.id}/{action}/", {"cue": cue.id})
        if 200 <= status < 300:
            self.log(f"Console fired {name}: {action.upper()} {name} {cue.label}".rstrip())
        else:
            detail = data.get("detail") if isinstance(data, dict) else None
            self.log(f"Console fired {name}; not recorded. {detail or f'The app answered {status}.'}")
