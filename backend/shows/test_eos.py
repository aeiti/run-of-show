import asyncio
import socket
import struct
from decimal import Decimal

import pytest
from django.core.management import CommandError, call_command
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from shows import services
from shows.eos import LengthFramer, OSCError, Relay, SlipFramer, cue_fire, parse_packet
from shows.management.commands.listen_eos import Command
from shows.models import CueEvent, Membership, Run


def osc_string(text):
    raw = text.encode() + b"\0"
    return raw + b"\0" * (-len(raw) % 4)


def osc(address, *args):
    """An OSC message as Eos would send it, with string, int and float arguments."""
    tags, body = ",", b""
    for arg in args:
        if isinstance(arg, str):
            tags, body = tags + "s", body + osc_string(arg)
        elif isinstance(arg, int):
            tags, body = tags + "i", body + struct.pack(">i", arg)
        else:
            tags, body = tags + "f", body + struct.pack(">f", arg)
    return osc_string(address) + osc_string(tags) + body


def bundle(*messages):
    return b"#bundle\0" + b"\0" * 7 + b"\1" + b"".join(struct.pack(">i", len(m)) + m for m in messages)


def fire(number, cue_list=1, label="", action="fire"):
    return osc(f"/eos/out/event/cue/{cue_list}/{number}/{action}", label)


# --- Parsing ---------------------------------------------------------------


def test_parses_a_message_and_its_arguments():
    assert parse_packet(osc("/eos/out/active/cue", 0.5)) == [("/eos/out/active/cue", [0.5])]
    assert parse_packet(fire("12.5", label="Lightning follow")) == [
        ("/eos/out/event/cue/1/12.5/fire", ["Lightning follow"])
    ]
    assert parse_packet(osc("/eos/out/user", 1)) == [("/eos/out/user", [1])]


def test_unpacks_bundles():
    packet = bundle(osc("/eos/out/pending/cue/1/2"), fire("1"))
    assert [address for address, _ in parse_packet(packet)] == ["/eos/out/pending/cue/1/2", "/eos/out/event/cue/1/1/fire"]


def test_rejects_bytes_that_arent_osc():
    with pytest.raises(OSCError):
        parse_packet(b"GO 5\n")


def test_length_framing_reassembles_packets_split_across_reads():
    a, b = fire("1"), fire("2")
    stream = struct.pack(">I", len(a)) + a + struct.pack(">I", len(b)) + b
    framer = LengthFramer()
    assert framer.feed(stream[:3]) == []
    assert framer.feed(stream[3 : len(a) + 6]) == [a]
    assert framer.feed(stream[len(a) + 6 :]) == [b]


def test_slip_framing_unescapes_and_splits_on_end():
    packet = fire("1") + b"\xc0\xdb"  # bytes that must be escaped inside a frame
    escaped = packet.replace(b"\xdb", b"\xdb\xdd").replace(b"\xc0", b"\xdb\xdc")
    framer = SlipFramer()
    assert framer.feed(b"\xc0" + escaped[:5]) == []
    assert framer.feed(escaped[5:] + b"\xc0" + fire("2") + b"\xc0") == [packet, fire("2")]


def test_cue_fire_reads_list_and_number_and_ignores_everything_else():
    assert cue_fire("/eos/out/event/cue/1/12.5/fire") == (1, Decimal("12.5"))
    assert cue_fire("/EOS/OUT/EVENT/CUE/2/7/FIRE") == (2, Decimal("7"))
    assert cue_fire("/eos/out/event/cue/1/7/stop") is None
    assert cue_fire("/eos/out/event/cue/1/7/resume") is None
    assert cue_fire("/eos/out/active/cue/1/7") is None
    assert cue_fire("/eos/out/event/cue/1/1.2.3/fire") is None


# --- Recording fires on the open run --------------------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def console(show, make_user):
    """A relay recording as Eos, an operator on the show, through the real API."""
    account = make_user("eos")
    Membership.objects.create(production=show.production, user=account, role=Membership.Role.OPERATOR)
    client = APIClient()

    def post(path, body):
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get_or_create(user=account)[0].key}")
        response = client.post(f"/api/{path}", body, format="json")
        return response.status_code, response.data

    logs, clock = [], Clock()
    relay = Relay(show.production, 1, post, logs.append, clock=clock)

    def send(*packets):
        for packet in packets:
            clock.now += 5
            relay.handle(packet)

    return type("Console", (), {"relay": relay, "send": staticmethod(send), "logs": logs, "clock": clock})


def recorded(run):
    return [(e.action, f"{e.cue_number.normalize():f}") for e in CueEvent.objects.filter(run=run).order_by("id")]


@pytest.mark.django_db
def test_fires_are_recorded_as_go_and_going_back_as_goto(show, console):
    console.send(fire("1"), fire("2"), fire("12.5"), fire("2"), fire("12"))
    # 12.5 skips 12; firing 2 again from 12.5 is the console going back.
    assert recorded(show.run) == [("go", "1"), ("go", "2"), ("go", "12.5"), ("goto", "2"), ("go", "12")]
    assert console.logs[-1] == "Console fired Q12: GO Q12 Cue 12"


@pytest.mark.django_db
def test_ignores_other_cue_lists_other_events_and_stray_bytes(show, console):
    console.send(fire("1", cue_list=2), fire("1", action="stop"), osc("/eos/out/active/cue/1/1", 0.5), b"hello")
    assert recorded(show.run) == []
    assert console.logs == ["Ignored 5 bytes: Not an OSC packet."]


@pytest.mark.django_db
def test_the_same_fire_twice_in_a_second_counts_once(show, console):
    console.send(fire("1"))
    console.clock.now += 0.2
    console.relay.handle(fire("1"))  # the standard and a custom cue event, or UDP and TCP both
    assert recorded(show.run) == [("go", "1")]
    console.send(fire("1"))  # seconds later it is a real refire
    assert recorded(show.run) == [("go", "1"), ("goto", "1")]


@pytest.mark.django_db
def test_a_cue_not_in_the_list_is_reported_not_recorded(show, console):
    console.send(fire("7.5"))
    assert recorded(show.run) == []
    assert console.logs == ["Console fired Q7.5; not recorded. Q7.5 isn't in this production's cue list."]


@pytest.mark.django_db
def test_records_on_the_newest_open_run(show, console):
    show.run.ended_at = show.run.created_at
    show.run.save()
    console.send(fire("1"))
    assert console.logs[-1] == "Console fired Q1; not recorded. No run is open. Start one on the board."

    newer = Run.objects.create(production=show.production, label="Preview 2")
    console.send(fire("1"))
    assert recorded(newer) == [("go", "1")]


@pytest.mark.django_db
def test_a_held_run_reports_the_app_refusing(show, console):
    console.send(fire("1"))
    services.hold(show.run, "Medical")
    console.send(fire("2"))
    assert recorded(show.run)[-1] == ("hold", "1")
    assert console.logs[-1] == "Console fired Q2; not recorded. The run is on hold. Resume it first."


# --- The command ----------------------------------------------------------


@pytest.mark.django_db
def test_refuses_an_account_that_cant_run_the_show(show, make_user):
    viewer = make_user("watcher")
    Membership.objects.create(production=show.production, user=viewer, role=Membership.Role.VIEWER)
    with pytest.raises(CommandError, match="can't run Show A"):
        call_command("listen_eos", production=show.production.id, user="watcher")
    with pytest.raises(CommandError, match="no production"):
        call_command("listen_eos", production=999, user="watcher")
    with pytest.raises(CommandError, match="no active account"):
        call_command("listen_eos", production=show.production.id, user="nobody")


class FakeRelay:
    def __init__(self):
        self.packets = []
        self.got = asyncio.Event()
        self.loop = None

    def handle(self, data):
        self.packets.append(data)
        self.loop.call_soon_threadsafe(self.got.set)


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_listens_on_udp():
    relay, port = FakeRelay(), free_port(socket.SOCK_DGRAM)
    relay.loop = asyncio.get_running_loop()
    options = {"no_udp": False, "bind": "127.0.0.1", "udp_port": port}
    task = asyncio.create_task(Command().listen(relay, options, None))
    await asyncio.sleep(0.1)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(fire("1"), ("127.0.0.1", port))
    await asyncio.wait_for(relay.got.wait(), 2)
    task.cancel()
    assert relay.packets == [fire("1")]


@pytest.mark.asyncio
@pytest.mark.parametrize("framing", ["1.0", "1.1"])
async def test_reads_from_the_console_over_tcp_without_sending_anything(framing):
    received = []

    async def console(reader, writer):
        packet = fire("1")
        if framing == "1.0":
            writer.write(struct.pack(">I", len(packet)) + packet)
        else:
            writer.write(b"\xc0" + packet + b"\xc0")
        await writer.drain()
        received.append(await reader.read(100))  # b"" once the listener disconnects
        writer.close()

    server = await asyncio.start_server(console, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    relay = FakeRelay()
    relay.loop = asyncio.get_running_loop()
    options = {"no_udp": True, "tcp_framing": framing}
    task = asyncio.create_task(Command().listen(relay, options, ("127.0.0.1", port)))
    await asyncio.wait_for(relay.got.wait(), 2)
    task.cancel()
    await asyncio.sleep(0.1)
    server.close()
    assert relay.packets == [fire("1")]
    assert received == [b""]  # the listener only disconnected
