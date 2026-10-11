"""Working out how long to wait from what a provider says about its rate limits.

All durations are in seconds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from email.utils import parsedate_to_datetime

MINUTE = 60.0
HOUR = 60 * MINUTE

MIN_COOLDOWN = 1.0
MAX_COOLDOWN = 24 * HOUR
DAILY_QUOTA_COOLDOWN = HOUR

_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "m": MINUTE, "h": HOUR}
_NUMBER = re.compile(r"\d+(\.\d+)?")
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
_DURATION = re.compile(r"(?:\d+(?:\.\d+)?(?:ms|s|m|h))+")


def parse_duration(value: str) -> float | None:
    """Parses "7.66s", "2m59.56s", "120ms" or a bare number of seconds."""
    s = value.strip()
    if _NUMBER.fullmatch(s):
        return float(s)
    if not _DURATION.fullmatch(s):
        return None
    return sum(float(n) * _UNIT_SECONDS[unit] for n, unit in _DURATION_PART.findall(s))


def parse_reset(value: str, now: float) -> float | None:
    """A reset value may be a duration, an epoch in seconds or milliseconds, or an HTTP date."""
    s = value.strip()
    if _NUMBER.fullmatch(s):
        n = float(s)
        if n > 1e12:
            return n / 1000 - now
        if n > 1e9:
            return n - now
        return n
    duration = parse_duration(s)
    if duration is not None:
        return duration
    try:
        return parsedate_to_datetime(s).timestamp() - now
    except (TypeError, ValueError):
        return None


def window_reset(headers: Mapping[str, str], now: float) -> float | None:
    """Time until an exhausted rate-limit window reopens, from x-ratelimit-* headers."""
    wait: float | None = None
    for suffix in ("-requests", "-tokens", ""):
        remaining = headers.get(f"x-ratelimit-remaining{suffix}")
        reset = headers.get(f"x-ratelimit-reset{suffix}")
        if remaining is None or reset is None:
            continue
        try:
            if float(remaining) > 0:
                continue
        except ValueError:
            continue
        seconds = parse_reset(reset, now)
        if seconds is not None and (wait is None or seconds > wait):
            wait = seconds
    return wait


def _retry_after_header(headers: Mapping[str, str], now: float) -> float | None:
    ms = headers.get("retry-after-ms")
    if ms is not None and _NUMBER.fullmatch(ms.strip()):
        return float(ms) / 1000
    retry_after = headers.get("retry-after")
    return None if retry_after is None else parse_reset(retry_after, now)


def _retry_after_body(body: str, now: float) -> float | None:
    # Gemini: "retryDelay": "34s"
    delay = re.search(r'"retryDelay"\s*:\s*"([^"]+)"', body)
    if delay:
        return parse_duration(delay.group(1))
    # Groq: "Please try again in 2m59.56s"
    again = re.search(r"try again in ((?:\d+(?:\.\d+)?(?:ms|s|m|h))+)", body, re.IGNORECASE)
    if again:
        return parse_duration(again.group(1))
    # OpenRouter puts the rate-limit headers inside the error body.
    try:
        reset = json.loads(body)["error"]["metadata"]["headers"]["X-RateLimit-Reset"]
    except (ValueError, KeyError, TypeError):
        return None
    return parse_reset(str(reset), now)


def rate_limit_cooldown(headers: Mapping[str, str], body: str, now: float) -> float | None:
    """How long to bench a target after a 429, or None if the upstream gave no hint."""
    wait = _retry_after_header(headers, now)
    if wait is None:
        wait = window_reset(headers, now)
    if wait is None:
        wait = _retry_after_body(body, now)
    if re.search(r"per[\s_-]?day|daily", body, re.IGNORECASE):
        wait = max(wait or 0.0, DAILY_QUOTA_COOLDOWN)
    return None if wait is None else clamp_cooldown(wait)


def clamp_cooldown(seconds: float) -> float:
    return min(MAX_COOLDOWN, max(MIN_COOLDOWN, seconds))


def backoff(base: float, failures: int, cap: float) -> float:
    return min(cap, base * float(2 ** max(0, failures - 1)))
