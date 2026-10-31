import asyncio
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from rest_framework.authtoken.models import Token

from shows.access import can
from shows.eos import LengthFramer, Relay, SlipFramer
from shows.models import Production

FRAMERS = {"1.0": LengthFramer, "1.1": SlipFramer}


class Command(BaseCommand):
    help = (
        "Follow an ETC Eos console: each cue it fires is recorded on the production's open run, "
        "as a GO by the given account. Only listens; nothing is sent to the console."
    )

    def add_arguments(self, parser):
        parser.add_argument("--production", type=int, required=True, help="Production id (the number in the board's URL).")
        parser.add_argument(
            "--user",
            required=True,
            help="Account the cues are recorded as. Give it its own account, an operator on the production: "
            "signing that account out elsewhere would cut the listener off.",
        )
        parser.add_argument("--cue-list", type=int, default=1, help="Eos cue list to follow (default 1).")
        parser.add_argument("--udp-port", type=int, default=4703, help="UDP port the console sends to (default 4703).")
        parser.add_argument("--bind", default="0.0.0.0", help="Address to listen on for UDP (default all).")
        parser.add_argument("--no-udp", action="store_true", help="Don't listen on UDP (use with --tcp).")
        parser.add_argument("--tcp", metavar="HOST:PORT", help="Also connect to the console's OSC TCP port and read from it.")
        parser.add_argument("--tcp-framing", choices=FRAMERS, default="1.0", help="The console's OSC TCP mode (default 1.0).")
        parser.add_argument("--api", default="http://localhost:8000/api", help="The app's API (default %(default)s).")

    def handle(self, *args, **options):
        production = Production.objects.filter(pk=options["production"]).first()
        if production is None:
            raise CommandError(f"There is no production {options['production']}.")
        user = get_user_model().objects.filter(username__iexact=options["user"], is_active=True).first()
        if user is None:
            raise CommandError(f"There is no active account named {options['user']}.")
        if not can(production, user, "operate"):
            raise CommandError(f"{user.username} can't run {production.name}. Add them as an operator first.")
        if options["no_udp"] and not options["tcp"]:
            raise CommandError("With --no-udp, give --tcp.")
        tcp = None
        if options["tcp"]:
            host, _, port = options["tcp"].rpartition(":")
            if not host or not port.isdigit():
                raise CommandError("--tcp takes HOST:PORT, such as 10.101.100.101:3032.")
            tcp = (host, int(port))

        api = options["api"].rstrip("/")

        def post(path, body):
            # Read the token each time: the account's token changes whenever it signs in or out.
            token, _ = Token.objects.get_or_create(user=user)
            request = urllib.request.Request(
                f"{api}/{path}",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Token {token.key}"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as e:
                try:
                    return e.code, json.loads(e.read() or b"{}")
                except ValueError:
                    return e.code, {}
            except (urllib.error.URLError, TimeoutError) as e:
                return 0, {"detail": f"Couldn't reach the app at {api}: {getattr(e, 'reason', e)}"}

        relay = Relay(production, options["cue_list"], post, self.log)
        self.log(f"Following Eos cue list {options['cue_list']} for {production.name}, recording as {user.username}.")
        try:
            asyncio.run(self.listen(relay, options, tcp))
        except KeyboardInterrupt:
            self.log("Stopped.")

    def log(self, text):
        self.stdout.write(f"{datetime.now():%H:%M:%S} {text}")

    async def listen(self, relay, options, tcp):
        loop = asyncio.get_running_loop()
        packets = asyncio.Queue()
        # One thread for the database and the API, so fires are recorded in the order they came.
        worker = ThreadPoolExecutor(max_workers=1)

        def handle(data):
            close_old_connections()
            relay.handle(data)

        tasks = []
        if not options["no_udp"]:
            await loop.create_datagram_endpoint(
                lambda: Datagrams(packets, self.log), local_addr=(options["bind"], options["udp_port"])
            )
            self.log(f"Listening for OSC on UDP {options['bind']}:{options['udp_port']}.")
        if tcp:
            tasks.append(asyncio.create_task(self.read_tcp(tcp, FRAMERS[options["tcp_framing"]], packets)))
        try:
            while True:
                data = await packets.get()
                await loop.run_in_executor(worker, handle, data)
        finally:
            for task in tasks:
                task.cancel()
            worker.shutdown(wait=False)

    async def read_tcp(self, address, framer_class, packets):
        """Stay connected to the console, reconnecting with backoff. Only reads."""
        host, port = address
        delay = 1
        while True:
            try:
                reader, writer = await asyncio.open_connection(host, port)
            except OSError as e:
                self.log(f"Couldn't connect to {host}:{port} ({e.strerror or e}); trying again in {delay}s.")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            self.log(f"Connected to the console at {host}:{port}.")
            delay = 1
            framer = framer_class()
            try:
                while chunk := await reader.read(65536):
                    for packet in framer.feed(chunk):
                        packets.put_nowait(packet)
            except OSError:
                pass
            finally:
                writer.close()
            self.log(f"Lost the connection to {host}:{port}; reconnecting.")


class Datagrams(asyncio.DatagramProtocol):
    def __init__(self, packets, log):
        self.packets = packets
        self.log = log
        self.sources = set()

    def datagram_received(self, data, addr):
        if addr[0] not in self.sources:
            self.sources.add(addr[0])
            self.log(f"Receiving OSC from {addr[0]}.")
        self.packets.put_nowait(data)
