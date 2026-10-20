"""urllib-compatible requests with owned, cancellable HTTP connections."""

from contextlib import contextmanager
from http.client import HTTPConnection, HTTPSConnection
import io
import select
import socket
import ssl
import threading
import time
from urllib.parse import urlparse
from urllib.request import HTTPHandler, HTTPSHandler, ProxyHandler, build_opener

from .base import BackendGenerationError


class _ResponseSocket:
    """Poll cancellably without timing out an otherwise healthy slow response.

    Windows shutdown alone does not reliably wake an outstanding socket read.
    This reader checks cancellation between short readiness waits, while urllib
    keeps its ordinary HTTP parsing, proxy handling and TLS verification.
    """

    def __init__(self, sock, cancelled, deadline):
        self.sock, self.cancelled = sock, cancelled
        # deadline is shared with the caller: it holds the time the request expires, and the caller pushes it
        # forward when the model makes real progress (keep-alive bytes alone never do).
        self.deadline = deadline
        self.readers = 0
        self.close_requested = False

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def makefile(self, mode, buffering=None):
        if mode != "rb":
            raise ValueError("Only binary HTTP response reads are supported.")
        owner = self

        class Reader(io.RawIOBase):
            def readable(self):
                return True

            def readinto(self, buffer):
                while True:
                    if owner.cancelled.is_set():
                        raise BackendGenerationError("The model request was interrupted.", completion_state="cancelled")
                    if time.monotonic() > owner.deadline.at:
                        owner.deadline.expire()
                        raise BackendGenerationError("The model request exceeded its total timeout.", completion_state="cancelled")
                    pending = getattr(owner.sock, "pending", None)
                    if (pending and pending()) or select.select([owner.sock], [], [], .1)[0]:
                        previous_timeout = owner.sock.gettimeout()
                        try:
                            owner.sock.settimeout(.1)
                            return owner.sock.recv_into(buffer)
                        except (TimeoutError, ssl.SSLWantReadError):
                            continue
                        finally:
                            owner.sock.settimeout(previous_timeout)

            def close(self):
                if not self.closed:
                    owner.readers -= 1
                    if owner.close_requested and owner.readers == 0:
                        owner.sock.close()
                super().close()

        self.readers += 1
        return io.BufferedReader(Reader())

    def close(self):
        self.close_requested = True
        if not self.readers:
            self.sock.close()


@contextmanager
def interruptible_urlopen(request, *, timeout, register, unregister):
    connections = []
    timed_out = threading.Event()

    class Deadline:
        at = time.monotonic() + timeout

        @staticmethod
        def expire():
            timed_out.set()
            for connection in list(connections):
                connection.stop_request()

    deadline = Deadline()

    def touch():
        """Real progress from the model: allow another full timeout period."""
        deadline.at = time.monotonic() + timeout

    def factory(base):
        class Connection(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.active_socket = None
                self.cancelled = threading.Event()
                self.interrupt = self.stop_request
                connections.append(self)
                register(self.interrupt)

            def stop_request(self):
                self.cancelled.set()
                sock = self.sock or self.active_socket
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

            def connect(self):
                if self.cancelled.is_set() or timed_out.is_set():
                    raise BackendGenerationError("The model request was interrupted.", completion_state="cancelled")
                super().connect()
                self.sock = _ResponseSocket(self.sock, self.cancelled, deadline)
                self.active_socket = self.sock
                if self.cancelled.is_set() or timed_out.is_set():
                    self.stop_request()
                    self.close()
                    raise BackendGenerationError("The model request was interrupted.", completion_state="cancelled")

        return Connection

    class HTTP(HTTPHandler):
        def http_open(self, req):
            return self.do_open(factory(HTTPConnection), req)

    class HTTPS(HTTPSHandler):
        def https_open(self, req):
            return self.do_open(factory(HTTPSConnection), req, context=self._context)

    # Loopback engines (the owned llama.cpp server, LM Studio) must never be routed through a system proxy.
    handlers = [HTTP(), HTTPS()]
    if (urlparse(request.full_url).hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}:
        handlers.insert(0, ProxyHandler({}))
    try:
        with build_opener(*handlers).open(request, timeout=timeout) as response:
            response.touch_deadline = touch
            yield response
        if timed_out.is_set():
            raise TimeoutError("The model request exceeded its total timeout.")
    except Exception as exc:
        if timed_out.is_set():
            raise TimeoutError("The model request exceeded its total timeout.") from exc
        raise
    finally:
        for connection in connections:
            unregister(connection.interrupt)
            connection.close()
