# Contributing to tierhop

## Set up

```
git clone https://github.com/sakshamm21/tier-hop.git
cd tier-hop
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check . && mypy
```

Python 3.10 or newer. The tests need no API keys and no network. `ruff format .` fixes formatting for you.

Bugs and ideas go in [issues](https://github.com/sakshamm21/tier-hop/issues). Security problems are reported privately; see [SECURITY.md](SECURITY.md). Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

- **No runtime dependencies.** The package uses only the standard library, which is what makes it install anywhere in seconds. A change that needs a third-party package at runtime will not be merged.
- **No account rotation.** tierhop uses one key per provider. Features for cycling several accounts of the same provider to multiply a free quota are out of scope.
- **Every behaviour change comes with a test.**
- Durations are in seconds everywhere. Config keys and Python names are `snake_case`.

## How a request flows

1. `Router.create` ([router.py](src/tierhop/router.py)) calls `resolve_providers` and `resolve_targets` ([providers.py](src/tierhop/providers.py)). A provider is active when its API key is set. Each active provider is asked for its model list, and every usable model becomes a `Target` (`provider/model`).
2. `Router.chat` picks the candidate targets for the requested `model` (`resolve`), then walks them in order, skipping any that are benched.
3. Each upstream call goes through a `Transport` ([transport.py](src/tierhop/transport.py)): a plain function `(method, url, headers, body, timeout) -> UpstreamResponse`. The default one uses `urllib`.
4. A success is returned to the caller straight away. A failure goes to `Router._judge`, which decides the failure kind and how long to bench the target or the whole provider. For a 429, the wait comes from `rate_limit_cooldown` ([limits.py](src/tierhop/limits.py)), which reads the provider's headers and error body.
5. When no candidate is left, `ExhaustedError` is raised with the attempts made and the time until the soonest target is free.

On top of the router:

- `Chat` ([chat.py](src/tierhop/chat.py)) builds the message list from its history, calls `Router.chat` and stores the exchange once the reply has arrived. `iter_text` turns a streamed response into text pieces.
- The proxy ([server.py](src/tierhop/server.py)) turns an HTTP request into a `Router.chat` call and copies the upstream response back, chunk by chunk for streams.
- The command line ([cli.py](src/tierhop/cli.py)) wires these together.

## Tests

| File | Covers |
| --- | --- |
| [tests/test_limits.py](tests/test_limits.py) | Parsing of every rate-limit hint format |
| [tests/test_router.py](tests/test_router.py) | Failover, cooldowns, model resolution, discovery |
| [tests/test_chat.py](tests/test_chat.py) | Conversation history and the streaming parser |
| [tests/test_server.py](tests/test_server.py) | The proxy over real HTTP on a local port |
| [tests/test_cli.py](tests/test_cli.py) | `init`, `check` and `.env` parsing |

Tests never call a real provider. They pass the router a fake transport that returns scripted responses, and a fake clock so cooldowns can be tested without waiting:

```python
def transport(method, url, headers, body, timeout):
    return UpstreamResponse.of(429, {"error": "slow down"}, {"Retry-After": "30"})


router = Router(targets, transport=transport, clock=lambda: now)
```

`UpstreamResponse.of(status, payload, headers)` builds a response from bytes, text or anything JSON-serializable. The `Harness` class in `tests/test_router.py` wraps this pattern and records the calls made.

Run one file or one test:

```
pytest tests/test_router.py
pytest -k "429"
```

## Adding a built-in provider

A provider qualifies if it has a recurring free tier (not one-time trial credit), an OpenAI-compatible `POST /chat/completions` with bearer-token authentication, and some way to list its models.

1. Add a `Preset` to `PRESETS` in [providers.py](src/tierhop/providers.py) with its base URL, the name of its API key variable and the page where a key is created.
   - If its listing mixes free and paid models, or chat and non-chat models, set `include` and `exclude` to regular expressions that keep only the usable ones.
   - If the listing is not at `<base_url>/models`, set `models_url`. Listings are read from a top-level array or from a `data`, `models` or `result` key; set `model_key` if the model id is not in the `id` field.
   - If the URL needs an account id or similar, write it as an `{ENV_VAR}` placeholder. The provider is switched on only when every variable is set.
2. Add its name to `DEFAULT_ORDER`.
3. Add the key variable to [.env.example](.env.example) and to the key table in [README.md](README.md).
4. Check how it reports rate limits. Send requests until you get a 429 and look at the headers and body. If the wait time is in a form `rate_limit_cooldown` does not already read, add it to [limits.py](src/tierhop/limits.py) with a test in `tests/test_limits.py` that uses the real header or body text.
5. Run `tierhop check` with a real key and include the output in your pull request.

Users can already add any provider through the config file, so a preset is only worth adding for a provider many people will want.

## Changing how failures are handled

The table in [docs/reference.md](docs/reference.md) under "How it picks a model" is the specification. If you change `Router._judge` or the cooldown lengths, update that table in the same change and add a test to `tests/test_router.py`.

## Before you open a pull request

- `pytest`, `ruff check .`, `ruff format --check .` and `mypy` pass. CI runs all four.
- New behaviour has a test, and the README or [docs/](docs/) describe it if users can see it.
- User-visible changes have a line under "Unreleased" in [CHANGELOG.md](CHANGELOG.md).
- Nothing was added to `dependencies` in `pyproject.toml`.
- No API keys in the diff. `.env` is ignored by git; keep it that way.
