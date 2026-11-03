"""Waking the server so the Eos console listeners start with it (startup.py)."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from shows.startup import DEFAULT_PORT, serving_port, wake


@pytest.mark.parametrize(
    "argv, environ, port",
    [
        # The autoreloader's child serves; the watcher above it doesn't.
        (["manage.py", "runserver", "0.0.0.0:5600"], {"RUN_MAIN": "true"}, 5600),
        (["manage.py", "runserver", "0.0.0.0:5600"], {}, None),
        # Without the reloader the one process serves.
        (["manage.py", "runserver", "8001", "--noreload"], {}, 8001),
        (["manage.py", "runserver", "--noreload"], {}, DEFAULT_PORT),
        (["manage.py", "runserver", "[::1]:9000"], {"RUN_MAIN": "true"}, 9000),
        # Other commands serve nothing.
        (["manage.py", "migrate"], {"RUN_MAIN": "true"}, None),
        (["pytest", "-q"], {}, None),
        (["manage.py"], {}, None),
    ],
)
def test_only_the_serving_process_wakes_the_server(argv, environ, port):
    assert serving_port(argv, environ) == port


class Recorder(BaseHTTPRequestHandler):
    paths = []

    def do_GET(self):
        Recorder.paths.append(self.path)
        # Any answer will do, as an unauthenticated /api/ gets a 401.
        self.send_response(401)
        self.end_headers()

    def log_message(self, *args):
        pass


def serve(server):
    threading.Thread(target=server.handle_request, daemon=True).start()


def test_wake_asks_the_server_for_a_page():
    Recorder.paths = []
    server = HTTPServer(("127.0.0.1", 0), Recorder)
    serve(server)
    assert wake(server.server_address[1], timeout=5) is True
    assert Recorder.paths == ["/api/"]
    server.server_close()


def test_wake_waits_for_the_server_to_come_up():
    Recorder.paths = []
    server = HTTPServer(("127.0.0.1", 0), Recorder, bind_and_activate=False)
    server.server_bind()
    port = server.server_address[1]
    # Nothing listens yet: the first tries are refused. The server comes up a moment later.
    timer = threading.Timer(0.4, lambda: (server.server_activate(), serve(server)))
    timer.start()
    assert wake(port, timeout=5, interval=0.1) is True
    assert Recorder.paths == ["/api/"]
    server.server_close()


def test_wake_gives_up_when_nothing_answers():
    server = HTTPServer(("127.0.0.1", 0), Recorder, bind_and_activate=False)
    server.server_bind()
    port = server.server_address[1]
    server.server_close()
    assert wake(port, timeout=0.3, interval=0.1) is False
