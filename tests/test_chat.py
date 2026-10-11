import asyncio
import json

import pytest

from tierhop import (
    Chat,
    ExhaustedError,
    Provider,
    Router,
    StreamError,
    Target,
    UpstreamResponse,
    iter_text,
)


def sse(*pieces, tail="data: [DONE]\n\n"):
    events = [
        "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}) + "\n\n"
        for piece in pieces
    ]
    return "".join(events) + tail


class Upstream:
    """Answers every request with the next scripted reply and records what was asked."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        target = Target(Provider("fake", "https://fake.test/v1"), "model")
        self.router = Router([target], transport=self.transport)

    def transport(self, method, url, headers, body, timeout):
        request = json.loads(body)
        self.requests.append(request)
        reply = self.replies.pop(0)
        if request["stream"]:
            return UpstreamResponse.of(200, reply, {"content-type": "text/event-stream"})
        return UpstreamResponse.of(200, {"choices": [{"message": {"content": reply}}]})


class Drip:
    """A response body that arrives in the given pieces."""

    def __init__(self, *pieces):
        self.pieces = list(pieces)
        self.closed = False

    def read1(self, size=-1):
        return self.pieces.pop(0) if self.pieces else b""

    def close(self):
        self.closed = True


def test_send_returns_the_reply_and_remembers_the_conversation():
    upstream = Upstream("Hi there", "You said hello")
    chat = Chat("Be brief.", router=upstream.router, temperature=0.2)

    assert chat.send("hello") == "Hi there"
    assert chat.last_target == "fake/model"
    assert chat.send("what did I say?") == "You said hello"

    second = upstream.requests[1]
    assert second["temperature"] == 0.2
    assert second["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "what did I say?"},
    ]


def test_stream_yields_pieces_and_remembers_the_full_reply():
    upstream = Upstream(sse("Hel", "lo", " world"))
    chat = Chat(router=upstream.router)
    assert list(chat.stream("hi")) == ["Hel", "lo", " world"]
    assert chat.messages[-1] == {"role": "assistant", "content": "Hello world"}


def test_a_failed_send_leaves_the_history_untouched():
    def transport(method, url, headers, body, timeout):
        return UpstreamResponse.of(429, {}, {"retry-after": "30"})

    target = Target(Provider("fake", "https://fake.test/v1"), "model")
    chat = Chat(router=Router([target], transport=transport))
    with pytest.raises(ExhaustedError):
        chat.send("hello")
    assert chat.messages == []


def test_old_turns_are_dropped():
    upstream = Upstream("one", "two", "three")
    chat = Chat(router=upstream.router, max_turns=1)
    for text in ("a", "b", "c"):
        chat.send(text)
    assert [m["content"] for m in upstream.requests[2]["messages"]] == ["b", "two", "c"]


def test_reset_forgets_history_but_keeps_the_system_prompt():
    upstream = Upstream("one", "two")
    chat = Chat("Be brief.", router=upstream.router)
    chat.send("a")
    chat.reset()
    chat.send("b")
    assert [m["role"] for m in upstream.requests[1]["messages"]] == ["system", "user"]


def test_stopping_a_stream_early_keeps_what_was_said():
    upstream = Upstream(sse("one ", "two ", "three"))
    chat = Chat(router=upstream.router)
    stream = chat.stream("count")
    assert next(stream) == "one "
    stream.close()
    assert chat.messages[-1]["content"] == "one "


def test_asend_works_from_asyncio():
    upstream = Upstream("Hi there")
    chat = Chat(router=upstream.router)
    assert asyncio.run(chat.asend("hello")) == "Hi there"


def test_iter_text_handles_events_split_across_chunks():
    data = sse("héllo", " wörld").encode()
    body = Drip(data[:9], data[9:40], data[40:41], data[41:])
    response = UpstreamResponse(200, {}, body)
    assert "".join(iter_text(response)) == "héllo wörld"
    assert body.closed


def test_iter_text_skips_comments_and_events_without_text():
    stream = (
        ": keep-alive\n\n"
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        + sse("ok", tail="")
        + 'data: {"choices":[],"usage":{"total_tokens":3}}\n\n'
        "data: [DONE]\n\n"
    )
    assert list(iter_text(UpstreamResponse.of(200, stream))) == ["ok"]


def test_iter_text_raises_on_an_error_event():
    stream = sse("partial", tail='data: {"error":{"message":"provider overloaded"}}\n\n')
    pieces = []
    with pytest.raises(StreamError, match="provider overloaded"):
        for piece in iter_text(UpstreamResponse.of(200, stream)):
            pieces.append(piece)
    assert pieces == ["partial"]
