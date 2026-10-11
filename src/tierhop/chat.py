"""A conversation that remembers its history, for building chatbots."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

from .router import Router
from .transport import UpstreamResponse


class StreamError(Exception):
    """A provider reported an error after it had started streaming a reply."""


def iter_text(response: UpstreamResponse) -> Iterator[str]:
    """Yields the text pieces of a streamed chat completion as they arrive."""
    buffer = b""
    for chunk in response.iter_chunks():
        *lines, buffer = (buffer + chunk).split(b"\n")
        for line in lines:
            yield from _text_of(line)
    yield from _text_of(buffer)


def _text_of(line: bytes) -> Iterator[str]:
    line = line.strip()
    if not line.startswith(b"data:"):
        return
    data = line[5:].strip()
    if not data or data == b"[DONE]":
        return
    try:
        event = json.loads(data)
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    if event.get("error"):
        error = event["error"]
        raise StreamError(error.get("message") if isinstance(error, dict) else str(error))
    for choice in event.get("choices") or []:
        text = (choice.get("delta") or {}).get("content")
        if text:
            yield text


class Chat:
    """One conversation. Use one Chat per user or chat window.

        chat = Chat("You are a helpful assistant.")
        print(chat.send("Hello"))
        for piece in chat.stream("Tell me more"):
            print(piece, end="", flush=True)

    Extra keyword arguments (temperature, max_tokens, ...) are sent with every request.
    """

    def __init__(
        self,
        system: str | None = None,
        *,
        model: str = "auto",
        router: Router | None = None,
        max_turns: int = 20,
        **params: Any,
    ) -> None:
        self.system = system
        self.model = model
        self.max_turns = max_turns
        """How many past exchanges are sent along. Older ones are dropped."""
        self.params = params
        self.messages: list[dict[str, str]] = []
        self.last_target: str | None = None
        """The "<provider>/<model>" that produced the latest reply."""
        self._router = router

    @property
    def router(self) -> Router:
        if self._router is None:
            from .config import default_router

            self._router = default_router()
        return self._router

    def send(self, text: str) -> str:
        """Sends a message and returns the whole reply."""
        result = self.router.chat(self._request(text, stream=False))
        self.last_target = result.target.id
        completion = result.response.json()
        reply = completion["choices"][0]["message"].get("content") or ""
        self._remember(text, reply)
        return reply

    def stream(self, text: str) -> Iterator[str]:
        """Sends a message and yields the reply piece by piece as it is generated."""
        result = self.router.chat(self._request(text, stream=True))
        self.last_target = result.target.id
        pieces: list[str] = []
        try:
            for piece in iter_text(result.response):
                pieces.append(piece)
                yield piece
        except GeneratorExit:
            pass  # the caller stopped reading; keep what was said so far
        finally:
            result.response.close()
        if pieces:
            self._remember(text, "".join(pieces))

    async def asend(self, text: str) -> str:
        """send() for asyncio apps such as Discord or Telegram bots."""
        return await asyncio.to_thread(self.send, text)

    def reset(self) -> None:
        """Forgets the conversation so far. The system prompt stays."""
        self.messages.clear()

    def _request(self, text: str, stream: bool) -> dict[str, Any]:
        system = [{"role": "system", "content": self.system}] if self.system else []
        user = {"role": "user", "content": text}
        return {
            **self.params,
            "model": self.model,
            "messages": [*system, *self.messages, user],
            "stream": stream,
        }

    def _remember(self, text: str, reply: str) -> None:
        self.messages += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply},
        ]
        keep = 2 * self.max_turns
        self.messages = self.messages[-keep:] if keep > 0 else []


def ask(prompt: str, system: str | None = None, **options: Any) -> str:
    """Answers a single question, with no conversation history."""
    return Chat(system, **options).send(prompt)
