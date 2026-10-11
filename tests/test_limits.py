import json
from email.utils import formatdate

import pytest

from tierhop.limits import parse_duration, parse_reset, rate_limit_cooldown, window_reset

NOW = 1_800_000_000.0


def test_parse_duration_reads_provider_formats():
    assert parse_duration("7.5s") == 7.5
    assert parse_duration("2m59.5s") == 179.5
    assert parse_duration("120ms") == pytest.approx(0.12)
    assert parse_duration("30") == 30
    assert parse_duration("soon") is None


def test_parse_reset_tells_durations_from_epochs_and_dates():
    assert parse_reset("45", NOW) == 45
    assert parse_reset(str(int((NOW + 60) * 1000)), NOW) == pytest.approx(60)
    assert parse_reset(str(int(NOW + 90)), NOW) == pytest.approx(90)
    assert parse_reset(formatdate(NOW + 5, usegmt=True), NOW) == pytest.approx(5)
    assert parse_reset("whenever", NOW) is None


def test_cooldown_prefers_retry_after():
    headers = {"retry-after": "12", "x-ratelimit-reset-requests": "5m"}
    assert rate_limit_cooldown(headers, "", NOW) == 12


def test_cooldown_uses_the_window_that_is_actually_empty():
    headers = {
        "x-ratelimit-remaining-requests": "14",
        "x-ratelimit-reset-requests": "6m",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "40s",
    }
    assert rate_limit_cooldown(headers, "", NOW) == 40


def test_cooldown_reads_hints_from_error_bodies():
    groq = '{"error":{"message":"Rate limit reached. Please try again in 1m2.5s."}}'
    assert rate_limit_cooldown({}, groq, NOW) == 62.5

    gemini = '[{"error":{"details":[{"retryDelay": "34s"}]}}]'
    assert rate_limit_cooldown({}, gemini, NOW) == 34

    reset = str(int((NOW + 90) * 1000))
    openrouter = json.dumps({"error": {"metadata": {"headers": {"X-RateLimit-Reset": reset}}}})
    assert rate_limit_cooldown({}, openrouter, NOW) == pytest.approx(90)


def test_cooldown_benches_daily_quotas_for_at_least_an_hour():
    body = '{"error":{"message":"Quota exceeded: requests per day","retryDelay": "20s"}}'
    assert rate_limit_cooldown({}, body, NOW) == 3600


def test_cooldown_is_none_without_a_hint():
    assert rate_limit_cooldown({}, "slow down", NOW) is None


def test_window_reset_ignores_windows_with_quota_left():
    headers = {"x-ratelimit-remaining-requests": "3", "x-ratelimit-reset-requests": "1m"}
    assert window_reset(headers, NOW) is None
