"""Picks a free model for each request and moves on when one runs out."""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .limits import HOUR, MINUTE, backoff, clamp_cooldown, rate_limit_cooldown, window_reset
from .providers import Target, resolve_providers, resolve_targets, setup_help
from .transport import Transport, UpstreamResponse, urllib_transport

# Two different models refusing the same request means the request is the problem.
MAX_REJECTIONS = 2

_MODEL_GONE = re.compile(r"decommission|not found|does not exist|no longer", re.IGNORECASE)

# What a transport raises when no usable response arrives.
TRANSPORT_ERRORS = (OSError, http.client.HTTPException)


@dataclass
class Attempt:
    target: str
    ok: bool
    seconds: float
    status: int | None = None
    kind: str | None = None
    """rate-limit, auth, missing, rejected, server or network."""
    error: str | None = None
    cooldown: float | None = None
    """How long the target (or its provider) was benched as a result."""


@dataclass
class Rejection:
    status: int
    body: str
    content_type: str


@dataclass
class ChatResult:
    response: UpstreamResponse
    target: Target
    attempts: list[Attempt]


@dataclass
class TargetStatus:
    id: str
    available: bool
    available_in: float
    requests: int
    successes: int
    last_error: str | None


class ExhaustedError(Exception):
    def __init__(
        self,
        message: str,
        attempts: list[Attempt],
        retry_after: float,
        rejection: Rejection | None = None,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.retry_after = retry_after
        """Seconds until the soonest benched target becomes available again."""
        self.rejection = rejection
        """Set when upstreams refused the request itself rather than running out of quota."""


@dataclass
class _State:
    cooldown_until: float = 0.0
    failures: int = 0
    requests: int = 0
    successes: int = 0
    last_error: str | None = None


@dataclass
class _Verdict:
    kind: str
    cooldown: float
    provider_wide: bool = False


@dataclass
class Router:
    targets: list[Target]
    aliases: Mapping[str, list[str]] = field(default_factory=dict)
    strategy: str = "priority"
    timeout: float = 60.0
    max_attempts: int = 10
    transport: Transport = urllib_transport
    clock: Callable[[], float] = time.time
    on_attempt: Callable[[Attempt], None] | None = None

    def __post_init__(self) -> None:
        self._states: dict[str, _State] = {}
        self._provider_cooldowns: dict[str, float] = {}
        self._cursor = 0
        self._lock = threading.Lock()

    @classmethod
    def create(
        cls,
        config: Mapping[str, Any] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        transport: Transport = urllib_transport,
        warn: Callable[[str], None] = lambda message: None,
        **options: Any,
    ) -> Router:
        """Builds a router from config and API keys in the environment, discovering models live."""
        config = config or {}
        providers = resolve_providers(config, os.environ if env is None else env)
        targets = resolve_targets(providers, transport, warn)
        for key in ("aliases", "strategy", "timeout", "max_attempts"):
            if key in config:
                options.setdefault(key, config[key])
        return cls(targets, transport=transport, **options)

    def chat(self, body: Mapping[str, Any]) -> ChatResult:
        """Sends a chat completion to the first available target.

        Moves to the next target whenever one is rate limited, out of quota or
        failing. The caller owns the returned response and must read or close it.
        """
        if not self.targets:
            raise ExhaustedError(
                f"No free models available. Set at least one provider API key:\n{setup_help()}",
                [],
                0,
            )
        candidates = self._candidates(body.get("model"))
        attempts: list[Attempt] = []
        rejection: Rejection | None = None
        rejections = 0

        for target in candidates:
            if len(attempts) >= self.max_attempts or rejections >= MAX_REJECTIONS:
                break
            with self._lock:
                if self._cooldown_left(target) > 0:
                    continue
                state = self._state(target)
                state.requests += 1
            started = self.clock()

            try:
                response = self._send(target, body)
            except TRANSPORT_ERRORS as err:
                with self._lock:
                    state.failures += 1
                    cooldown = backoff(10, state.failures, 5 * MINUTE)
                    state.cooldown_until = self.clock() + cooldown
                    state.last_error = str(err) or type(err).__name__
                self._record(
                    attempts,
                    target,
                    started,
                    kind="network",
                    error=state.last_error,
                    cooldown=cooldown,
                )
                continue

            if response.ok:
                with self._lock:
                    state.failures = 0
                    state.successes += 1
                    # The provider told us this call used up the window: don't wait for the 429.
                    spent = window_reset(response.headers, self.clock())
                    if spent is not None:
                        state.cooldown_until = self.clock() + clamp_cooldown(spent)
                self._record(attempts, target, started, ok=True, status=response.status)
                return ChatResult(response, target, attempts)

            try:
                text = response.text()
            except TRANSPORT_ERRORS:
                text = ""
            with self._lock:
                verdict = self._judge(response, text, state)
                state.last_error = f"{response.status} {_summarize(text)}"
                if verdict.kind == "rejected":
                    rejections += 1
                elif verdict.provider_wide:
                    until = self.clock() + verdict.cooldown
                    self._provider_cooldowns[target.provider.name] = until
                else:
                    state.cooldown_until = self.clock() + verdict.cooldown
            if verdict.kind == "rejected" and rejection is None:
                content_type = response.headers.get("content-type", "application/json")
                rejection = Rejection(response.status, text, content_type)
            self._record(
                attempts,
                target,
                started,
                status=response.status,
                kind=verdict.kind,
                error=state.last_error,
                cooldown=verdict.cooldown or None,
            )

        with self._lock:
            waits = [left for t in candidates if (left := self._cooldown_left(t)) > 0]
        message = (
            "Every target that was tried refused the request."
            if rejection
            else f"All {len(candidates)} free targets are rate limited or failing."
        )
        raise ExhaustedError(message, attempts, min(waits, default=0.0), rejection)

    def complete(self, body: Mapping[str, Any]) -> Any:
        """Like chat(), but returns the parsed completion. Not for streaming requests."""
        return self.chat({**body, "stream": False}).response.json()

    def status(self) -> list[TargetStatus]:
        with self._lock:
            statuses = []
            for target in self.targets:
                state = self._state(target)
                left = max(0.0, self._cooldown_left(target))
                statuses.append(
                    TargetStatus(
                        target.id,
                        left == 0,
                        left,
                        state.requests,
                        state.successes,
                        state.last_error,
                    )
                )
            return statuses

    def model_names(self) -> list[str]:
        """Model names clients may send: "auto", aliases, provider names and target ids."""
        providers = dict.fromkeys(t.provider.name for t in self.targets)
        return ["auto", *self.aliases, *providers, *(t.id for t in self.targets)]

    def resolve(self, model: str | None = None) -> list[Target]:
        """Maps a requested model to targets.

        Accepts "auto", an alias, a provider name, a "<provider>/<model>" id or
        a bare model id. Anything unrecognized falls back to every target, so
        existing apps work without changing their model name.
        """
        if not model or model == "auto":
            return self.targets
        matched: dict[Target, None] = {}
        for name in self.aliases.get(model, [model]):
            for target in self.targets:
                if name in (target.id, target.provider.name, target.model):
                    matched[target] = None
        return list(matched) or self.targets

    def _candidates(self, model: str | None) -> list[Target]:
        targets = self.resolve(model)
        if self.strategy != "round-robin" or len(targets) < 2:
            return targets
        with self._lock:
            start = self._cursor % len(targets)
            self._cursor += 1
        return targets[start:] + targets[:start]

    def _send(self, target: Target, body: Mapping[str, Any]) -> UpstreamResponse:
        headers = {"Content-Type": "application/json", **target.provider.auth_headers()}
        payload = json.dumps({**body, "model": target.model}).encode()
        url = f"{target.provider.base_url}/chat/completions"
        return self.transport("POST", url, headers, payload, self.timeout)

    def _judge(self, response: UpstreamResponse, text: str, state: _State) -> _Verdict:
        status = response.status
        if status == 429:
            cooldown = rate_limit_cooldown(response.headers, text, self.clock())
            if cooldown is None:
                state.failures += 1
                cooldown = backoff(30, state.failures, 15 * MINUTE)
            return _Verdict("rate-limit", cooldown)
        if status in (401, 402):
            return _Verdict("auth", HOUR, provider_wide=True)
        if status == 403:
            return _Verdict("auth", HOUR)
        model_gone = "model" in text.lower() and _MODEL_GONE.search(text)
        if status == 404 or (status == 400 and model_gone):
            return _Verdict("missing", 6 * HOUR)
        if status in (400, 413, 422):
            return _Verdict("rejected", 0.0)
        state.failures += 1
        return _Verdict("server", backoff(10, state.failures, 5 * MINUTE))

    def _record(
        self,
        attempts: list[Attempt],
        target: Target,
        started: float,
        ok: bool = False,
        **details: Any,
    ) -> None:
        attempt = Attempt(target.id, ok, self.clock() - started, **details)
        attempts.append(attempt)
        if self.on_attempt:
            self.on_attempt(attempt)

    def _cooldown_left(self, target: Target) -> float:
        until = max(
            self._state(target).cooldown_until,
            self._provider_cooldowns.get(target.provider.name, 0.0),
        )
        return until - self.clock()

    def _state(self, target: Target) -> _State:
        return self._states.setdefault(target.id, _State())


def _summarize(text: str) -> str:
    message: Any = text
    try:
        parsed = json.loads(text)
        error = (parsed[0] if isinstance(parsed, list) else parsed)["error"]
        message = error if isinstance(error, str) else error["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    return " ".join(str(message).split())[:200]
