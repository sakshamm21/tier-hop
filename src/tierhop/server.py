"""An OpenAI-compatible HTTP server in front of a Router."""

from __future__ import annotations

import contextlib
import hmac
import json
import math
import os
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .providers import setup_help
from .router import TRANSPORT_ERRORS, ExhaustedError, Router
from .transport import UpstreamResponse

MAX_BODY_BYTES = 20 * 1024 * 1024

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Expose-Headers": "x-tierhop-target, x-tierhop-attempts",
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    router: Router
    api_key: str | None = None

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def handle(self) -> None:
        # The client may hang up on a kept-alive connection.
        with contextlib.suppress(ConnectionError):
            super().handle()

    def do_OPTIONS(self) -> None:
        self._send(204, b"")

    def do_GET(self) -> None:
        if not self._authorized():
            return
        path = self._path()
        if path in ("/v1/models", "/models"):
            data = [
                {"id": name, "object": "model", "created": 0, "owned_by": "tierhop"}
                for name in self.router.model_names()
            ]
            self._send_json(200, {"object": "list", "data": data})
        elif path in ("/", "/status"):
            self._send_json(200, {"targets": [asdict(s) for s in self.router.status()]})
        else:
            self._not_found(path)

    def do_POST(self) -> None:
        if not self._authorized():
            return
        path = self._path()
        if path not in ("/v1/chat/completions", "/chat/completions"):
            # The unread request body would be parsed as the next request.
            self.close_connection = True
            return self._not_found(path)

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY_BYTES:
            self.close_connection = True
            return self._send_error(413, "Request body is too large or has no valid length.")
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError as err:
            return self._send_error(400, f"Invalid request body: {err}")
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return self._send_error(400, "Request body needs a messages array.")

        try:
            result = self.router.chat(body)
        except ExhaustedError as err:
            return self._send_exhausted(err)

        response = result.response
        headers = {
            "Content-Type": response.headers.get("content-type", "application/json"),
            "Cache-Control": "no-cache",
            "x-tierhop-target": result.target.id,
            "x-tierhop-attempts": str(len(result.attempts)),
        }
        if not body.get("stream"):
            try:
                data = response.read()
            except TRANSPORT_ERRORS as err:
                return self._send_error(502, f"{result.target.id} dropped the connection: {err}")
            return self._send(response.status, data, headers)
        self._stream(response, headers)

    def _stream(self, response: UpstreamResponse, headers: dict[str, str]) -> None:
        self.send_response(response.status)
        for name, value in {**CORS, **headers, "Transfer-Encoding": "chunked"}.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            for chunk in response.iter_chunks():
                self.wfile.write(b"%x\r\n%b\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except TRANSPORT_ERRORS:
            # Either side went away mid-stream; there is nothing left to send.
            self.close_connection = True
        finally:
            # Stops paying for upstream tokens once the client has gone away.
            response.close()

    def _send_exhausted(self, err: ExhaustedError) -> None:
        if err.rejection:
            headers = {"Content-Type": err.rejection.content_type}
            return self._send(err.rejection.status, err.rejection.body.encode(), headers)
        status = 503 if not err.attempts and err.retry_after == 0 else 429
        payload = {
            "error": {
                "message": str(err),
                "type": "rate_limit_error",
                "code": "all_targets_exhausted",
            },
            "attempts": [asdict(a) for a in err.attempts],
        }
        retry_after = str(max(1, math.ceil(err.retry_after)))
        self._send_json(status, payload, {"Retry-After": retry_after})

    def _authorized(self) -> bool:
        if not self.api_key:
            return True
        given = self.headers.get("Authorization", "")
        if hmac.compare_digest(given.encode(), f"Bearer {self.api_key}".encode()):
            return True
        # The unread request body would be parsed as the next request.
        self.close_connection = True
        self._send_error(401, "Missing or wrong API key for this tierhop proxy.")
        return False

    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    def _not_found(self, path: str) -> None:
        self._send_error(404, f"tierhop does not serve {self.command} {path}")

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": {"message": message, "type": "invalid_request_error"}})

    def _send_json(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
        headers = {"Content-Type": "application/json", **(headers or {})}
        self._send(status, json.dumps(payload).encode(), headers)

    def _send(self, status: int, data: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in {**CORS, **(headers or {}), "Content-Length": str(len(data))}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)


class _Server(ThreadingHTTPServer):
    # On Windows this option lets a second process bind a port that is already in use.
    allow_reuse_address = os.name != "nt"


def create_server(
    router: Router, host: str = "127.0.0.1", port: int = 4141, api_key: str | None = None
) -> ThreadingHTTPServer:
    """Returns a server ready for serve_forever(). Port 0 picks a free port.

    With api_key set, clients must send it as their OpenAI API key.
    """
    handler = type("Handler", (_Handler,), {"router": router, "api_key": api_key})
    return _Server((host, port), handler)


_background: tuple[ThreadingHTTPServer, str] | None = None
_background_lock = threading.Lock()


def start(
    router: Router | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    api_key: str | None = None,
    set_env: bool = True,
) -> str:
    """Runs the proxy in a background thread of this process and returns its base URL.

    With set_env, OPENAI_BASE_URL and OPENAI_API_KEY are pointed at it, so an
    OpenAI client created afterwards uses the free models with no other change.
    Calling start() again returns the URL of the proxy that is already running.
    """
    global _background
    with _background_lock:
        if _background is None:
            if router is None:
                from .config import default_router

                router = default_router()
            if not router.targets:
                raise RuntimeError(
                    "No free models available. Set at least one provider API key in the "
                    f"environment or in a .env file in this folder:\n{setup_help()}"
                )
            server = create_server(router, host, port, api_key)
            threading.Thread(target=server.serve_forever, daemon=True, name="tierhop").start()
            _background = (server, f"http://{host}:{server.server_address[1]}/v1")
        url = _background[1]
    if set_env:
        os.environ["OPENAI_BASE_URL"] = url
        os.environ["OPENAI_API_KEY"] = api_key or os.environ.get("OPENAI_API_KEY") or "tierhop"
    return url


def stop() -> None:
    """Stops the proxy that start() launched, if there is one."""
    global _background
    with _background_lock:
        if _background is not None:
            _background[0].shutdown()
            _background[0].server_close()
            _background = None
