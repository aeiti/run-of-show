import asyncio
import socket
import struct
from decimal import Decimal

import pytest
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework.authtoken.models import Token

from config.asgi import application
from shows import services
from shows.console import Supervisor
from shows.eos import LengthFramer, OSCError, Relay, SlipFramer, cue_fire, cue_progress, describe, parse_packet
from shows.models import ConsoleEvent, CueEvent, EosConsole, Membership, Run
from shows.tests import client_for


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
def console(show):
    """A relay for the show's console, with a clock the test moves."""
    logs, clock = [], Clock()
    relay = Relay(show.production.id, 1, lambda text, problem: logs.append((text, problem)), clock=clock)

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
    assert console.logs[-1] == ("Console fired Q12: GO Q12 Cue 12", False)


def logged(run):
    return [(c.kind, c.text) for c in ConsoleEvent.objects.filter(run=run).order_by("id")]


@pytest.mark.django_db
def test_other_show_control_events_go_in_the_log_but_move_no_cue(show, console):
    console.send(
        fire("1", cue_list=2, label="Sound"),
        fire("1", action="stop"),
        fire("1", action="resume"),
        osc("/eos/out/event/macro/12"),
        osc("/eos/out/event/sub/3", 1),
        osc("/eos/out/event/show/saved", "C:/shows/mexodus.esf"),
        osc("/eos/out/active/cue/1/1", 0.5),  # fade progress: not an event
        osc("/eos/out/pending/cue/1/2"),  # state, not an event
    )
    assert console.relay.handle(b"hello") is False
    assert recorded(show.run) == []
    assert logged(show.run) == [
        ("show_control", "Eos fired list 2 Q1 Sound"),
        ("show_control", "Eos stopped list 1 Q1"),
        ("show_control", "Eos resumed list 1 Q1"),
        ("show_control", "Eos ran macro 12"),
        ("show_control", "Eos submaster 3 bump on"),
        ("show_control", "Eos show saved: C:/shows/mexodus.esf"),
    ]
    assert console.logs == []


@pytest.mark.django_db
def test_recorded_fires_say_the_console_fired_them_and_skipped_ones_are_logged(show, console):
    console.send(fire("1"), fire("7.5"))
    event = CueEvent.objects.get(run=show.run)
    assert (event.action, event.source) == ("go", "console")
    # The run's start, for boards that only hear the live message.
    show.run.refresh_from_db()
    assert show.run.started_at == event.fired_at
    assert logged(show.run) == [("show_control", "Console fired Q7.5; not recorded. Q7.5 isn't in this production's cue list.")]
    detail = client_for(show.owner).get(f"/api/runs/{show.run.id}/").data
    assert detail["events"][0]["source"] == "console"
    assert detail["console_events"][0]["text"].startswith("Console fired Q7.5")


@pytest.mark.django_db
def test_with_no_run_open_nothing_is_logged(show, console):
    show.run.ended_at = show.run.created_at
    show.run.save()
    console.send(osc("/eos/out/event/macro/1"))
    assert not ConsoleEvent.objects.exists()


@pytest.mark.django_db
def test_the_run_export_includes_console_events_in_time_order(show, console):
    console.send(fire("1"), osc("/eos/out/event/macro/4"))
    rows = client_for(show.owner).get(f"/api/runs/{show.run.id}/export/").content.decode().splitlines()
    assert rows[0].endswith(",note,source")
    assert rows[1].split(",")[2:] == ["go", "1", "Cue 1", "", "console"]
    assert rows[2].split(",")[2:] == ["console", "", "", "Eos ran macro 4", "show_control"]


def test_describe_names_eos_events_and_ignores_the_rest():
    assert describe("/eos/out/event/cue/1/12.5/fire", ["Lightning"]) == "Eos fired list 1 Q12.5 Lightning"
    assert describe("/eos/out/event/relay/2/1", [0]) == "Eos relay 2 group 1 on"
    assert describe("/eos/out/event/sub/4", [0]) == "Eos submaster 4 bump off"
    assert describe("/eos/out/event/something/new", [3]) == "Eos /eos/out/event/something/new 3"
    assert describe("/eos/out/active/cue", [0.5]) is None
    assert describe("/eos/out/user", [1]) is None


def test_cue_progress_reads_eos_text_and_floats():
    text = "/eos/out/active/cue/text"
    assert cue_progress(text, ["1/195 SUNRISE 5.0 50%"]) == (1, Decimal("195"), 0.5, 5.0)
    # Labels with spaces, and ones ending in a number.
    assert cue_progress(text, ["1/12.5 Lightning take 3 0.4 91%"]) == (1, Decimal("12.5"), 0.91, 0.4)
    assert cue_progress(text, ["1/7 2.5 0%"]) == (1, Decimal("7"), 0.0, 2.5)
    assert cue_progress(text, ["2/7 Fog 1:30.5 10%"]) == (2, Decimal("7"), 0.1, 90.5)
    # At 100% the time is the cue's whole time, not what's left.
    assert cue_progress(text, ["1/195 SUNRISE 12.0 100%"]) == (1, Decimal("195"), 1.0, None)
    assert cue_progress("/eos/out/active/cue/1/195", [0.25]) == (1, Decimal("195"), 0.25, None)
    for address, args in [
        ("/eos/out/active/cue", [0.91]),  # names no cue
        (text, [""]),
        (text, ["SUNRISE 50%"]),
        (text, ["1/195 SUNRISE 5.0"]),
        (text, [0.5]),
        ("/eos/out/active/cue/1/195", ["half"]),
        ("/eos/out/active/cue/1/1.2.3", [0.5]),
        ("/eos/out/event/cue/1/195/fire", ["SUNRISE"]),
    ]:
        assert cue_progress(address, args) is None, (address, args)


@pytest.fixture
def broadcasts(monkeypatch):
    sent = []
    monkeypatch.setattr("shows.eos.live.broadcast", lambda production_id, message: sent.append(message))
    return sent


def progress_text(cue, percent, remaining, cue_list=1):
    return osc("/eos/out/active/cue/text", f"{cue_list}/{cue} Cue {cue} {remaining} {percent}%")


@pytest.mark.django_db
def test_progress_reaches_boards_once_per_update_and_records_nothing(show, console, broadcasts):
    console.send(fire("1"))
    broadcasts.clear()
    # Eos sends each update as text and as a float, and the console here sends every packet twice.
    update = bundle(progress_text("1", 40, "3.0"), osc("/eos/out/active/cue/1/1", 0.4000000059604645))
    console.relay.handle(update)
    console.relay.handle(update)
    console.relay.handle(progress_text("1", 100, "5.0"))
    cue = show.cues["1"].id
    assert broadcasts == [
        {"type": "cue.progress", "run": show.run.id, "cue": cue, "progress": 0.4, "remaining": 3.0},
        {"type": "cue.progress", "run": show.run.id, "cue": cue, "progress": 1.0, "remaining": None},
    ]
    assert recorded(show.run) == [("go", "1")]
    assert logged(show.run) == []
    # Firing the cue again starts its progress over, even at a percent already sent.
    console.send(fire("1"))
    broadcasts.clear()
    console.relay.handle(progress_text("1", 100, "5.0"))
    assert len(broadcasts) == 1


@pytest.mark.django_db
def test_progress_for_another_list_no_run_or_unknown_cue_is_dropped(show, console, broadcasts):
    console.relay.handle(progress_text("1", 50, "1.0", cue_list=2))
    console.relay.handle(progress_text("7.5", 50, "1.0"))
    show.run.ended_at = show.run.created_at
    show.run.save()
    console.relay.handle(progress_text("2", 50, "1.0"))
    assert broadcasts == []


@pytest.mark.django_db
def test_the_same_fire_twice_in_a_second_counts_once(show, console):
    console.send(fire("1"))
    console.clock.now += 0.2
    console.relay.handle(fire("1"))  # the standard and a custom cue event, say
    assert recorded(show.run) == [("go", "1")]
    console.send(fire("1"))  # seconds later it is a real refire
    assert recorded(show.run) == [("go", "1"), ("goto", "1")]


@pytest.mark.django_db
def test_a_copy_with_other_messages_between_still_counts_once(show, console):
    # Seen on a real desk: each packet arrived twice, so the fire's copy came
    # after another event, and was recorded as a GOTO of the same cue.
    console.send(fire("1"))
    for packet in (osc("/eos/out/event/macro/5"), fire("1"), osc("/eos/out/event/macro/5")):
        console.clock.now += 0.1
        console.relay.handle(packet)
    assert recorded(show.run) == [("go", "1")]
    assert logged(show.run) == [("show_control", "Eos ran macro 5")]


@pytest.mark.django_db
def test_a_cue_not_in_the_list_is_reported_not_recorded(show, console):
    console.send(fire("7.5"))
    assert recorded(show.run) == []
    assert console.logs == [("Console fired Q7.5; not recorded. Q7.5 isn't in this production's cue list.", True)]


@pytest.mark.django_db
def test_records_on_the_newest_open_run(show, console):
    show.run.ended_at = show.run.created_at
    show.run.save()
    console.send(fire("1"))
    assert console.logs[-1] == ("Console fired Q1; not recorded. No run is open. Start one on the board.", True)

    newer = Run.objects.create(production=show.production, label="Preview 2")
    console.send(fire("1"))
    assert recorded(newer) == [("go", "1")]


@pytest.mark.django_db
def test_a_held_run_records_nothing(show, console):
    console.send(fire("1"))
    services.hold(show.run, "Medical")
    console.send(fire("2"))
    assert recorded(show.run)[-1] == ("hold", "1")
    assert console.logs[-1] == ("Console fired Q2; not recorded. The run is on hold. Resume it first.", True)


# --- Settings ---------------------------------------------------------------


def console_url(production):
    return f"/api/productions/{production.id}/console/"


@pytest.mark.django_db
def test_settings_start_off_and_only_editors_change_them(show, make_user):
    viewer = make_user("viewer")
    Membership.objects.create(production=show.production, user=viewer, role=Membership.Role.VIEWER)
    seen = client_for(viewer).get(console_url(show.production))
    assert seen.status_code == 200
    assert (seen.data["enabled"], seen.data["transport"], seen.data["port"], seen.data["cue_list"]) == (False, "udp", 4703, 1)
    assert seen.data["status"]["state"] == "off"
    assert client_for(viewer).put(console_url(show.production), {"enabled": True}, format="json").status_code == 403

    saved = client_for(show.owner).put(
        console_url(show.production), {"enabled": True, "port": 4710, "cue_list": 2}, format="json"
    )
    assert saved.status_code == 200 and (saved.data["enabled"], saved.data["port"], saved.data["cue_list"]) == (True, 4710, 2)
    assert EosConsole.objects.get(production=show.production).port == 4710


@pytest.mark.django_db
def test_tcp_needs_the_consoles_address(show):
    response = client_for(show.owner).put(console_url(show.production), {"transport": "tcp", "port": 3032}, format="json")
    assert response.status_code == 400 and "IP address" in str(response.data["host"])


@pytest.mark.django_db
def test_two_productions_cant_listen_on_one_udp_port(show):
    from shows.models import Production

    other = Production.objects.create(owner=show.owner, name="Show B")
    client = client_for(show.owner)
    assert client.put(console_url(other), {"enabled": True, "port": 4710}, format="json").status_code == 200
    refused = client.put(console_url(show.production), {"enabled": True, "port": 4710}, format="json")
    assert refused.status_code == 400 and "Show B is already listening on UDP port 4710" in str(refused.data["port"])
    # Saved but off, or over TCP, it doesn't hold the port.
    assert client.put(console_url(show.production), {"enabled": False, "port": 4710}, format="json").status_code == 200
    tcp = {"enabled": True, "transport": "tcp", "host": "10.0.0.5", "port": 4710}
    assert client.put(console_url(show.production), tcp, format="json").status_code == 200


@pytest.mark.django_db
def test_copies_and_exports_leave_the_console_behind(show):
    EosConsole.objects.create(production=show.production, enabled=True)
    client = client_for(show.owner)
    copy = client.post(f"/api/productions/{show.production.id}/duplicate/", {}, format="json")
    assert not EosConsole.objects.filter(production=copy.data["id"]).exists()
    assert "console" not in str(client.get(f"/api/productions/{show.production.id}/export/").json()).lower()


# --- Listening, in the server process ---------------------------------------


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# database_sync_to_async closes the connection after, so none is left open at teardown.
@database_sync_to_async
def configure(production, **fields):
    EosConsole.objects.update_or_create(production=production, defaults=fields)


@database_sync_to_async
def events(run):
    return recorded(run)


@database_sync_to_async
def console_log(run):
    return logged(run)


async def board(production, user):
    socket_ = WebsocketCommunicator(application, f"/ws/productions/{production.id}/", headers=[(b"origin", b"http://localhost:3200")])
    assert (await socket_.connect())[0]
    await socket_.send_json_to({"type": "auth", "token": await sync_to_async(lambda: Token.objects.get_or_create(user=user)[0].key)()})
    assert (await socket_.receive_json_from())["type"] == "ready"
    return socket_


async def until(socket_, predicate):
    while True:
        message = await socket_.receive_json_from(timeout=2)
        if predicate(message):
            return message


@pytest.fixture
def local_bind(settings):
    settings.EOS_BIND_ADDRESS = "127.0.0.1"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_udp_console_fire_reaches_open_boards(show, local_bind):
    port = free_port(socket.SOCK_DGRAM)
    await configure(show.production, enabled=True, port=port)
    screen = await board(show.production, show.owner)
    supervisor = Supervisor()
    supervisor.ensure_started()
    await supervisor.starting
    status = await until(screen, lambda m: m["type"] == "console")
    assert status["status"]["state"] == "listening" and status["status"]["detail"] == f"Listening on UDP port {port}"

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(fire("1"), ("127.0.0.1", port))
    heard = await until(screen, lambda m: m["type"] == "console")
    assert heard["status"]["heard"] is not None
    event = await until(screen, lambda m: m["type"] == "run.event")
    assert (event["run"], event["event"]["action"], event["event"]["cue_number"]) == (show.run.id, "go", "1")
    assert event["state"]["active_number"] == "1"
    assert await events(show.run) == [("go", "1")]
    # The message and what came of it, newest first, for the settings dialog.
    recent = supervisor.recent(show.production.id)
    assert recent[0]["result"] == "Console fired Q1: GO Q1 Cue 1" and recent[0]["problem"] is False
    assert (recent[1]["address"], recent[1]["args"]) == ("/eos/out/event/cue/1/1/fire", [""])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(b"GO 2", ("127.0.0.1", port))
    for _ in range(40):
        if supervisor.recent(show.production.id)[0].get("note"):
            break
        await asyncio.sleep(0.05)
    assert supervisor.recent(show.production.id)[0]["note"] == "4 bytes from 127.0.0.1, not OSC"

    # Turning it off frees the port and tells the boards.
    await configure(show.production, enabled=False, port=port)
    await supervisor.apply(show.production.id)
    assert (await until(screen, lambda m: m["type"] == "console"))["status"]["state"] == "off"
    assert supervisor.recent(show.production.id) == []
    # The listener's start and stop are in the run's log.
    for _ in range(40):
        if len(await console_log(show.run)) == 2:
            break
        await asyncio.sleep(0.05)
    assert await console_log(show.run) == [
        ("network", f"Listening on UDP port {port}"),
        ("network", "Stopped following the console"),
    ]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", port))
    await supervisor.stop_all()
    await screen.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_port_already_in_use_is_reported(show, local_bind):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as taken:
        taken.bind(("127.0.0.1", 0))
        port = taken.getsockname()[1]
        await configure(show.production, enabled=True, port=port)
        supervisor = Supervisor()
        supervisor.ensure_started()
        await supervisor.starting
        status = supervisor.status(show.production.id)
        assert status["state"] == "error" and f"UDP port {port}" in status["detail"]
        await supervisor.stop_all()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("framing", ["1.0", "1.1"])
async def test_a_tcp_console_is_read_from_and_sent_nothing(show, framing):
    received, connected = [], asyncio.Event()

    async def eos(reader, writer):
        connected.set()
        packet = fire("1")
        writer.write(struct.pack(">I", len(packet)) + packet if framing == "1.0" else b"\xc0" + packet + b"\xc0")
        await writer.drain()
        received.append(await reader.read(100))  # b"" once the listener lets go
        writer.close()

    server = await asyncio.start_server(eos, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    await configure(show.production, enabled=True, transport="tcp", host="127.0.0.1", port=port, framing=framing)
    supervisor = Supervisor()
    supervisor.ensure_started()
    await supervisor.starting
    await asyncio.wait_for(connected.wait(), 2)
    for _ in range(40):
        if await events(show.run):
            break
        await asyncio.sleep(0.05)
    assert await events(show.run) == [("go", "1")]
    assert supervisor.status(show.production.id)["state"] == "connected"
    assert (await console_log(show.run))[0] == ("network", f"Connected to 127.0.0.1:{port} (TCP)")
    await supervisor.stop_all()
    await asyncio.sleep(0.1)
    server.close()
    assert received == [b""]
