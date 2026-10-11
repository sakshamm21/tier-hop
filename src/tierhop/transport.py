"""The HTTP client the router talks to providers with. Standard library only."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO

from ._version import __version__

# Some providers sit behind a firewall that rejects urllib's default user agent.
USER_AGENT = f"tierhop/{__version__}"


@dataclass
class UpstreamResponse:
    """A provider's response. Headers are keyed in lower case."""

    status: int
    headers: dict[str, str]
    body: BinaryIO

    @classmethod
    def of(
        cls, status: int, payload: Any = b"", headers: Mapping[str, str] | None = None
    ) -> UpstreamResponse:
        """Builds a response from bytes, text or a JSON-serializable value."""
        if isinstance(payload, str):
            payload = payload.encode()
        elif not isinstance(payload, bytes):
            payload = json.dumps(payload).encode()
        lowered = {"content-type": "application/json"}
        lowered.update({k.lower(): v for k, v in (headers or {}).items()})
        return cls(status, lowered, io.BytesIO(payload))

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def read(self) -> bytes:
        try:
            return self.body.read()
        finally:
            self.close()

    def text(self) -> str:
        return self.read().decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.read())

    def iter_chunks(self, size: int = 65536) -> Iterator[bytes]:
        """Yields data as it arrives, without waiting to fill a buffer."""
        try:
            while chunk := self.body.read1(size):  # type: ignore[attr-defined]
                yield chunk
        finally:
            self.close()

    def close(self) -> None:
        self.body.close()


# (method, url, headers, body, timeout in seconds) -> response.
# Must return error statuses as responses and raise OSError when no response arrives.
Transport = Callable[[str, str, dict[str, str], "bytes | None", float], UpstreamResponse]


def urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> UpstreamResponse:
    request = urllib.request.Request(
        url, data=body, method=method, headers={"User-Agent": USER_AGENT, **headers}
    )
    try:
        raw = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as err:
        raw = err
    return UpstreamResponse(raw.status, {k.lower(): v for k, v in raw.headers.items()}, raw)
