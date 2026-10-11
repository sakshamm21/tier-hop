import json
from urllib.parse import urlsplit

import pytest

from tierhop import ExhaustedError, Provider, Router, Target, UpstreamResponse

REQUEST = {"model": "auto", "messages": [{"role": "user", "content": "hello"}]}


def ok(_model=None):
    return UpstreamResponse.of(200, {"choices": [{"message": {"content": "hi"}}]})


def targets(*ids):
    result = []
    for target_id in ids:
        name, _, model = target_id.partition("/")
        result.append(Target(Provider(name, f"https://{name}.test/v1", f"{name}-key"), model))
    return result


class Harness:
    """A fake upstream: one handler per provider host, plus a log of the calls made."""

    def __init__(self, ids, script, **options):
        self.script = script
        self.calls = []
        self.now = 1_800_000_000.0
        self.router = Router(
            targets(*ids), transport=self.transport, clock=lambda: self.now, **options
        )

    def transport(self, method, url, headers, body, timeout):
        host = urlsplit(url).hostname.removesuffix(".test")
        model = json.loads(body)["model"]
        self.calls.append(f"{host}/{model}")
        reply = self.script[host](model)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_uses_the_first_target_and_rewrites_the_model_name():
    h = Harness(["a/m1", "b/m2"], {"a": ok, "b": ok})
    result = h.router.chat(REQUEST)
    assert result.target.id == "a/m1"
    assert h.calls == ["a/m1"]
    assert REQUEST["model"] == "auto"


def test_sends_the_provider_key_as_a_bearer_token():
    seen = {}

    def transport(method, url, headers, body, timeout):
        seen.update(headers)
        return ok()

    Router(targets("a/m1"), transport=transport).chat(REQUEST)
    assert seen["Authorization"] == "Bearer a-key"


def test_fails_over_on_429_and_benches_for_the_advertised_time():
    limited = lambda _: UpstreamResponse.of(429, {"error": "slow down"}, {"Retry-After": "30"})
    h = Harness(["a/m1", "b/m2"], {"a": limited, "b": ok})

    first = h.router.chat(REQUEST)
    assert first.target.id == "b/m2"
    assert first.attempts[0].kind == "rate-limit"
    assert first.attempts[0].cooldown == 30

    h.router.chat(REQUEST)
    assert h.calls == ["a/m1", "b/m2", "b/m2"], "benched target is not retried"

    h.now += 31
    h.router.chat(REQUEST)
    assert h.calls[-2] == "a/m1", "target is retried once its cooldown passes"


def test_fails_over_on_network_and_server_errors():
    h = Harness(
        ["a/m1", "b/m2", "c/m3"],
        {
            "a": lambda _: ConnectionResetError("connection reset"),
            "b": lambda _: UpstreamResponse.of(503, {"error": "overloaded"}),
            "c": ok,
        },
    )
    result = h.router.chat(REQUEST)
    assert result.target.id == "c/m3"
    assert [a.kind for a in result.attempts] == ["network", "server", None]


def test_a_rejected_key_benches_every_model_of_that_provider():
    denied = lambda _: UpstreamResponse.of(401, {"error": {"message": "invalid api key"}})
    h = Harness(["a/m1", "a/m2", "b/m3"], {"a": denied, "b": ok})
    assert h.router.chat(REQUEST).target.id == "b/m3"
    assert h.calls == ["a/m1", "b/m3"]


def test_a_missing_model_is_benched_without_affecting_its_siblings():
    def a(model):
        if model == "old":
            return UpstreamResponse.of(404, {"error": {"message": "model not found"}})
        return ok()

    h = Harness(["a/old", "a/new"], {"a": a})
    assert h.router.chat(REQUEST).target.id == "a/new"
    h.router.chat(REQUEST)
    assert h.calls == ["a/old", "a/new", "a/new"]


def test_raises_with_the_soonest_retry_time_when_everything_is_benched():
    h = Harness(
        ["a/m1", "b/m2"],
        {
            "a": lambda _: UpstreamResponse.of(429, {}, {"retry-after": "120"}),
            "b": lambda _: UpstreamResponse.of(429, {}, {"retry-after": "45"}),
        },
    )
    with pytest.raises(ExhaustedError) as caught:
        h.router.chat(REQUEST)
    assert caught.value.retry_after == 45
    assert len(caught.value.attempts) == 2

    with pytest.raises(ExhaustedError):
        h.router.chat(REQUEST)
    assert len(h.calls) == 2, "no upstream calls while everything is benched"


def test_stops_after_two_refusals_and_surfaces_the_upstream_error():
    bad = lambda _: UpstreamResponse.of(400, {"error": {"message": "messages: invalid role"}})
    h = Harness(["a/m1", "b/m2", "c/m3"], {"a": bad, "b": bad, "c": ok})
    with pytest.raises(ExhaustedError) as caught:
        h.router.chat(REQUEST)
    assert caught.value.rejection.status == 400
    assert "invalid role" in caught.value.rejection.body
    assert h.calls == ["a/m1", "b/m2"]
    assert all(s.available for s in h.router.status()), "bad requests do not bench targets"


def test_benches_ahead_of_time_when_a_success_reports_an_empty_window():
    spent = lambda _: UpstreamResponse.of(
        200, {}, {"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "1m"}
    )
    h = Harness(["a/m1", "b/m2"], {"a": spent, "b": ok})
    h.router.chat(REQUEST)
    h.router.chat(REQUEST)
    assert h.calls == ["a/m1", "b/m2"]


def test_backs_off_longer_on_repeated_unexplained_429s():
    limited = lambda _: UpstreamResponse.of(429, "slow down")
    h = Harness(["a/m1"], {"a": limited})
    cooldowns = []
    for _ in range(3):
        with pytest.raises(ExhaustedError) as caught:
            h.router.chat(REQUEST)
        cooldowns.append(caught.value.attempts[0].cooldown)
        h.now += cooldowns[-1] + 1
    assert cooldowns == [30, 60, 120]


def test_respects_max_attempts():
    down = lambda _: UpstreamResponse.of(500, {})
    h = Harness(["a/m1", "b/m2", "c/m3"], {"a": down, "b": down, "c": ok}, max_attempts=2)
    with pytest.raises(ExhaustedError):
        h.router.chat(REQUEST)
    assert len(h.calls) == 2


def test_resolves_aliases_providers_ids_and_bare_model_names():
    router = Router(targets("a/m1", "a/m2", "b/m2", "c/m3"), aliases={"fast": ["c", "a/m1"]})
    ids = lambda model: [t.id for t in router.resolve(model)]
    assert ids("auto") == ["a/m1", "a/m2", "b/m2", "c/m3"]
    assert ids("a") == ["a/m1", "a/m2"]
    assert ids("b/m2") == ["b/m2"]
    assert ids("m2") == ["a/m2", "b/m2"]
    assert ids("fast") == ["c/m3", "a/m1"]
    assert ids("gpt-4o-mini") == ids("auto"), "unknown names fall back to every target"


def test_round_robin_rotates_the_starting_target():
    h = Harness(["a/m1", "b/m2"], {"a": ok, "b": ok}, strategy="round-robin")
    for _ in range(3):
        h.router.chat(REQUEST)
    assert h.calls == ["a/m1", "b/m2", "a/m1"]


def test_complete_returns_the_parsed_body():
    h = Harness(["a/m1"], {"a": ok})
    assert h.router.complete(REQUEST)["choices"][0]["message"]["content"] == "hi"


def test_no_targets_raises():
    with pytest.raises(ExhaustedError, match="GROQ_API_KEY"):
        Router([]).chat(REQUEST)


LISTINGS = {
    "openrouter.ai": ["vendor/paid-model", "vendor/free-model:free", "vendor/safety-guard:free"],
    "generativelanguage.googleapis.com": ["models/gemini-flash", "models/gemini-pro"],
}


def test_create_discovers_models_and_keeps_only_usable_ones():
    def transport(method, url, headers, body, timeout):
        assert method == "GET" and url.endswith("/models")
        ids = LISTINGS[urlsplit(url).hostname]
        return UpstreamResponse.of(200, {"data": [{"id": i} for i in ids]})

    router = Router.create(
        {"providers": {"local": {"base_url": "http://localhost:11434/v1", "models": ["llama"]}}},
        env={"OPENROUTER_API_KEY": "or-key", "GEMINI_API_KEY": "g-key"},
        transport=transport,
    )
    assert [t.id for t in router.targets] == [
        "gemini/gemini-flash",
        "openrouter/vendor/free-model:free",
        "local/llama",
    ]


def test_create_applies_config_order_and_options():
    router = Router.create(
        {
            "order": ["b", "a"],
            "strategy": "round-robin",
            "max_attempts": 3,
            "providers": {
                "a": {"base_url": "http://a.test/v1/", "models": ["m1"]},
                "b": {"base_url": "http://b.test/v1", "models": ["m2"]},
                "c": {"base_url": "http://c.test/v1", "models": ["m3"], "enabled": False},
            },
        },
        env={},
    )
    assert [t.id for t in router.targets] == ["b/m2", "a/m1"]
    assert router.targets[1].provider.base_url == "http://a.test/v1"
    assert (router.strategy, router.max_attempts) == ("round-robin", 3)


def test_create_skips_a_provider_whose_discovery_fails():
    warnings = []
    router = Router.create(
        env={"GROQ_API_KEY": "bad"},
        transport=lambda *args: UpstreamResponse.of(401, {}),
        warn=warnings.append,
    )
    assert router.targets == []
    assert "groq: model discovery failed" in warnings[0]


def test_a_provider_with_url_placeholders_needs_every_variable():
    env = {"CLOUDFLARE_API_TOKEN": "token"}
    assert Router.create(env=env, transport=lambda *args: ok()).targets == []

    seen = []

    def transport(method, url, headers, body, timeout):
        seen.append(url)
        models = [
            {"id": "uuid-1", "name": "@cf/meta/llama-chat", "task": {"name": "Text Generation"}},
            {"id": "uuid-2", "name": "@cf/baai/bge-embed"},
        ]
        return UpstreamResponse.of(200, {"success": True, "result": models})

    router = Router.create(env={**env, "CLOUDFLARE_ACCOUNT_ID": "acct"}, transport=transport)
    assert [t.id for t in router.targets] == ["cloudflare/@cf/meta/llama-chat"]
    assert "/accounts/acct/ai/models/search" in seen[0]
    assert router.targets[0].provider.base_url.endswith("/accounts/acct/ai/v1")


def test_discovery_reads_listings_that_are_not_openai_shaped():
    def transport(method, url, headers, body, timeout):
        assert url.startswith("https://api.cohere.com/v1/models")
        models = [
            {"name": "command-new", "endpoints": ["chat"]},
            {"name": "command-old", "endpoints": ["chat"], "is_deprecated": True},
        ]
        return UpstreamResponse.of(200, {"models": models})

    router = Router.create(env={"COHERE_API_KEY": "key"}, transport=transport)
    assert [t.id for t in router.targets] == ["cohere/command-new"]
    assert router.targets[0].provider.base_url == "https://api.cohere.ai/compatibility/v1"


def test_every_built_in_provider_is_complete():
    from tierhop import DEFAULT_ORDER, PRESETS

    assert sorted(DEFAULT_ORDER) == sorted(PRESETS)
    for preset in PRESETS.values():
        assert preset.base_url.startswith("https://") and preset.keys_url.startswith("https://")
        assert preset.api_key_env.isupper()
