# tierhop

[![CI](https://github.com/sakshamm21/tier-hop/actions/workflows/ci.yml/badge.svg)](https://github.com/sakshamm21/tier-hop/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Build chatbots and other LLM features on free models, without babysitting rate limits.

tierhop puts the free tiers of nine LLM providers behind one interface. When a model hits its rate limit or runs out of quota, the next request goes to another model, and the first one is used again once its limit resets.

- Plugs into a chatbot you already have: two added lines in Python, or one environment variable in any language.
- Works with the OpenAI SDK and anything else that speaks the OpenAI API.
- Has a Python `Chat` class that keeps conversation history for you.
- Finds the currently available free models itself, so there is no model list to maintain.
- Runs on your own machine and has no dependencies outside the Python standard library.

You bring your own free API keys. tierhop does not come with any, and it never sends your keys anywhere except to the provider they belong to.

```
your app  ──►  tierhop  ──►  Groq          rate limited, benched 42s
                        ──►  Cerebras      ok
                             Gemini
                             Mistral
                             OpenRouter, NVIDIA, Hugging Face, Cohere, Cloudflare
```

## Contents

- [Get started](#get-started)
- [Free providers](#free-providers)
- [Add it to a chatbot you already have](#add-it-to-a-chatbot-you-already-have)
- [What you can build](#what-you-can-build)
  - [A chatbot in Python](#a-chatbot-in-python)
  - [A chatbot for many users](#a-chatbot-for-many-users)
  - [A chatbot in any language, through the proxy](#a-chatbot-in-any-language-through-the-proxy)
  - [One-off tasks](#one-off-tasks)
  - [An existing OpenAI app or tool](#an-existing-openai-app-or-tool)
- [Customize it](#customize-it)
- [Run the proxy on a server](#run-the-proxy-on-a-server)
- [How it picks a model](#how-it-picks-a-model)
- [Command reference](#command-reference)
- [Configuration reference](#configuration-reference)
- [Python reference](#python-reference)
- [Troubleshooting](#troubleshooting)
- [Limits](#limits)
- [Work on tierhop](#work-on-tierhop)
- [Project](#project)

## Get started

Requires Python 3.10 or newer.

**1. Install from GitHub**

```
pip install git+https://github.com/sakshamm21/tier-hop.git
```

The repository is named `tier-hop`; the package you import and the command you run are both `tierhop`.

**2. Add at least one free API key**

```
tierhop init
```

This creates a `.env` file in the current folder. Open it and paste in a key from any provider in the [list below](#free-providers). One is enough; more providers means more free quota to fall back on.

```
GROQ_API_KEY=your-key-here
GEMINI_API_KEY=your-key-here
```

Keys already set as environment variables work too, and take priority over the file.

**3. Check that the keys work**

```
tierhop check
```

It sends one small request per provider and prints which ones answered.

**4. Chat**

```
tierhop chat
```

That opens a chatbot in your terminal and shows which model answered each message. If it works there, it will work in your own project.

## Free providers

These are built in. Each is switched on by putting its key in `.env`; the ones you leave empty are skipped. They are tried in this order unless you [change it](#change-which-provider-is-tried-first).

| Provider | Variable in `.env` | Create a key at | Good to know |
| --- | --- | --- | --- |
| Groq | `GROQ_API_KEY` | https://console.groq.com/keys | Very fast responses |
| Cerebras | `CEREBRAS_API_KEY` | https://cloud.cerebras.ai | Very fast responses |
| Google Gemini | `GEMINI_API_KEY` | https://aistudio.google.com/apikey | Only the Flash models are used by default |
| Mistral | `MISTRAL_API_KEY` | https://console.mistral.ai/api-keys | The free plan lets Mistral train on your requests |
| OpenRouter | `OPENROUTER_API_KEY` | https://openrouter.ai/keys | Only models ending in `:free` are used |
| NVIDIA | `NVIDIA_API_KEY` | https://build.nvidia.com/settings/api-keys | Large catalog; models that no longer respond are skipped automatically |
| Hugging Face | `HF_TOKEN` | https://huggingface.co/settings/tokens | Free accounts get a small monthly credit, not a rate limit |
| Cohere | `COHERE_API_KEY` | https://dashboard.cohere.com/api-keys | Trial keys are for non-commercial use |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` | https://dash.cloudflare.com/profile/api-tokens | Needs both values; the account id is shown in the Cloudflare dashboard |

Free limits differ per provider and change often, so they are not listed here; each provider shows your current limits in its dashboard. tierhop does not need to know them: it reacts to what the provider reports.

Providers that give one-time trial credit instead of a recurring free tier (SambaNova, Fireworks, Nebius, DeepSeek, AI21 and others) are not built in, because they stop working when the credit runs out. You can still add any of them, or any other OpenAI-compatible service, with [a few lines of config](#add-another-provider-or-a-local-model).

## Add it to a chatbot you already have

Pick the row that matches your bot. In every case the only setup is the keys in `.env`.

| Your chatbot | What to do |
| --- | --- |
| Python, using the OpenAI SDK, LangChain or another OpenAI-compatible library | Add two lines: [`tierhop.start()`](#python-two-added-lines) |
| Any other language, or a tool where you can only change settings | Run `tierhop` next to it and set [one environment variable](#any-language-one-environment-variable) |
| Python, calling a provider's API by hand, or not written yet | Use the [`Chat` class](#a-chatbot-in-python) |

### Python: two added lines

```python
import tierhop

tierhop.start()

# The rest of your bot stays as it is.
from openai import OpenAI

client = OpenAI()
```

`tierhop.start()` runs tierhop inside your bot's own process and sets `OPENAI_BASE_URL` and `OPENAI_API_KEY`, which the OpenAI SDK reads when a client is created. So call it before you create the client. The sync and async clients, streaming and tool calls all work, and your existing model name can stay: names tierhop does not know are treated as `auto`.

`start()` returns the address it is listening on, for libraries that want it passed in:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(base_url=tierhop.start(), api_key="unused", model="auto")
```

Runnable version: [examples/existing_openai_bot.py](examples/existing_openai_bot.py).

### Any language: one environment variable

Start tierhop in a terminal and leave it running:

```
tierhop
```

Then start your bot with these two variables set. The official OpenAI SDKs for Python and JavaScript read them on their own, so the bot's code does not change:

```
OPENAI_BASE_URL=http://127.0.0.1:4141/v1
OPENAI_API_KEY=unused
```

If your bot or tool has settings for an OpenAI connection instead, enter the same address as the base URL, any text as the API key, and `auto` as the model.

To run tierhop without installing it first, if you have [uv](https://docs.astral.sh/uv/):

```
uvx --from git+https://github.com/sakshamm21/tier-hop.git tierhop
```

## What you can build

### A chatbot in Python

```python
from tierhop import Chat

chat = Chat("You are a helpful assistant.")

print(chat.send("Hi, my name is Sam."))
print(chat.send("What is my name?"))  # it remembers the conversation
```

To show the reply as it is generated:

```python
for piece in chat.stream("Tell me a short story."):
    print(piece, end="", flush=True)
```

`Chat` reads the `.env` file from the folder you run your script in. Full example: [examples/terminal_chatbot.py](examples/terminal_chatbot.py).

When every free model is rate limited, `send` and `stream` raise `ExhaustedError`. Its `retry_after` is the number of seconds until the first model is available again:

```python
from tierhop import Chat, ExhaustedError

try:
    reply = chat.send(text)
except ExhaustedError as err:
    reply = f"I'm out of free quota for now. Try again in {err.retry_after:.0f} seconds."
```

### A chatbot for many users

Keep one `Chat` per user so conversations do not mix. Discord, Telegram and Slack libraries call you inside an async function, so use `asend`, which does not block other users while a reply is generated:

```python
from tierhop import Chat

chats: dict[str, Chat] = {}


async def reply_to(user_id: str, text: str) -> str:
    chat = chats.setdefault(user_id, Chat("You are a helpful assistant."))
    return await chat.asend(text)
```

Call `reply_to` from your library's message handler. Runnable version: [examples/multi_user_bot.py](examples/multi_user_bot.py).

### A chatbot in any language, through the proxy

Start the proxy:

```
tierhop
```

Then point any OpenAI client at `http://127.0.0.1:4141/v1`. The API key can be any text; your real keys stay with tierhop.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:4141/v1", api_key="unused")

reply = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Hello"}],
)
```

```js
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "http://127.0.0.1:4141/v1", apiKey: "unused" });
```

Streaming, tool calls and other request fields are passed through unchanged. Browsers can call the proxy directly. Only `/v1/chat/completions` is proxied.

Full examples: [examples/openai_sdk_chatbot.py](examples/openai_sdk_chatbot.py), and [examples/web_chatbot.html](examples/web_chatbot.html), a chat page in one HTML file that you open in a browser while the proxy runs.

### One-off tasks

For classifying, summarizing, translating or extracting, where there is no conversation, use `ask`:

```python
from tierhop import ask

label = ask(
    "Arrived two days late and the box was crushed.",
    system="Classify the review as positive, negative or neutral. Reply with one word.",
    temperature=0,
)
```

Full example: [examples/one_off_tasks.py](examples/one_off_tasks.py).

### An existing OpenAI app or tool

Anything that lets you set an OpenAI base URL can run on tierhop: agent frameworks, chat front ends, editor plugins, your own scripts. Start the proxy and use these settings:

| Setting | Value |
| --- | --- |
| Base URL | `http://127.0.0.1:4141/v1` |
| API key | any text (or the proxy key, if you set one) |
| Model | `auto` |

If the tool insists on a specific model name such as `gpt-4o-mini`, leave it. tierhop treats names it does not know as `auto`.

## Customize it

All of this is optional. Settings go in a `tierhop.config.json` file in the folder you run tierhop from. The full list of keys is in the [configuration reference](#configuration-reference).

### Give the bot a personality

The first argument to `Chat` is the system prompt. Extra arguments are sent with every request:

```python
chat = Chat(
    "You are Pixel, a cheerful support bot for a game studio. Answer in two sentences.",
    temperature=0.7,
    max_tokens=300,
)
```

In the terminal: `tierhop chat --system "You are Pixel, a cheerful support bot."`

### Choose which models answer

tierhop uses models in the order each provider lists them, which says nothing about quality. Run `tierhop models` to see what is available, then pin the ones you want, best first:

```json
{
  "providers": {
    "groq": { "models": ["<model-id-you-prefer>", "<second-choice>"] }
  }
}
```

To filter instead of listing, use regular expressions on the model ids:

```json
{
  "providers": {
    "openrouter": { "include": "gemma|nemotron", "exclude": "nano" }
  }
}
```

### Change which provider is tried first

```json
{ "order": ["gemini", "groq"] }
```

Providers you leave out follow in the default order. To switch one off, set `"enabled": false` for it under `providers`.

### Offer a fast bot and a smart bot

Aliases are names for groups of providers or models. Clients ask for them in the `model` field:

```json
{
  "aliases": {
    "fast": ["cerebras", "groq"],
    "smart": ["gemini/<model-id>", "openrouter/<model-id>"]
  }
}
```

```python
quick = Chat("Answer briefly.", model="fast")
```

### Add another provider or a local model

Any OpenAI-compatible endpoint works, including a model running on your own machine. Give it a name, a `base_url` and the models to use:

```json
{
  "providers": {
    "ollama": { "base_url": "http://localhost:11434/v1", "models": ["<local-model>"] },
    "another": {
      "base_url": "https://api.example.com/v1",
      "api_key_env": "ANOTHER_API_KEY"
    }
  },
  "order": ["groq", "another", "ollama"]
}
```

Leave out `models` to have tierhop discover them from the endpoint's `/models` listing. Putting a local model last in `order` gives you a fallback that never runs out.

A provider with trial credit is added the same way. For example, SambaNova:

```json
{
  "providers": {
    "sambanova": { "base_url": "https://api.sambanova.ai/v1", "api_key_env": "SAMBANOVA_API_KEY" }
  }
}
```

### Spread requests across providers

By default every request starts from the top of the list, so the first provider takes all the traffic until it is rate limited. To rotate the starting point instead:

```json
{ "strategy": "round-robin" }
```

### Save and restore a conversation

`chat.messages` is a plain list of `{"role", "content"}` dictionaries:

```python
import json

with open("conversation.json", "w") as file:
    json.dump(chat.messages, file)

with open("conversation.json") as file:
    chat.messages = json.load(file)
```

`max_turns` (default 20) is the number of past exchanges sent with each request. Lower it if replies fail on long conversations; free models often have small limits.

### Configure from code instead of a file

`Router.create` takes the same keys as the config file. Pass the router to `Chat`:

```python
from tierhop import Chat, Router

router = Router.create(
    {"order": ["gemini", "groq"], "strategy": "round-robin"},
    on_attempt=print,  # called for every upstream call, including failed ones
)
chat = Chat("You are a helpful assistant.", router=router)
```

## Run the proxy on a server

If your bot runs somewhere other than your own machine, the proxy has to accept outside connections. Set a key so that only your bot can use it:

```
tierhop --host 0.0.0.0 --port 8080 --api-key choose-a-long-random-string
```

The same settings can come from the environment, which is how most hosting services pass them: `HOST`, `PORT` and `TIERHOP_API_KEY`, next to the provider keys.

Clients then send that key as their OpenAI API key:

```python
client = OpenAI(
    base_url="https://your-server.example.com/v1", api_key="choose-a-long-random-string"
)
```

Do not put the proxy key in a web page: anyone who opens the page can read it. For a public website, call the proxy from your own backend.

## How it picks a model

At startup tierhop asks each provider which models it serves, so the list does not go stale when providers add or retire models.

Each request walks the list in order and uses the first model that is not benched. What happens on a failure depends on the response:

| Upstream response | What tierhop does |
| --- | --- |
| 429 | Benches that model until the reset time the provider reports, then tries the next. Without a reset time it backs off from 30 seconds up to 15 minutes. A daily-quota message benches the model for at least an hour. |
| 401, 402 | Benches every model of that provider for an hour. |
| 403 | Benches that model for an hour. |
| 404, or a "model not found" 400 | Benches that model for six hours. |
| 400, 413, 422 | Tries the next model without benching. If a second model also refuses, the request is the problem and the upstream error is returned as is. |
| 5xx, timeout, network error | Backs off from 10 seconds up to 5 minutes and tries the next. |

A success that reports zero remaining requests or tokens benches the model right away, without waiting for the 429.

If every model is benched, the proxy answers `429` with a `Retry-After` header for the soonest reset, and the Python API raises `ExhaustedError`.

### The `model` field

| Value | Meaning |
| --- | --- |
| `auto` or omitted | Any model, in priority order |
| `groq` | Any model from that provider |
| `groq/<model-id>` | That model only |
| `<model-id>` | That model on whichever providers serve it |
| an alias from your config | The targets listed for that alias |
| anything else | Treated as `auto`, so existing apps work without changing their model name |

## Command reference

| Command | What it does |
| --- | --- |
| `tierhop init` | Creates `.env` with a line per provider key. On an existing file it only adds the missing lines. |
| `tierhop check` | Sends one small request per provider and reports which keys work. |
| `tierhop models` | Lists the free models found, as `provider/model`. |
| `tierhop chat` | Chatbot in the terminal. `/reset` clears the conversation, `/exit` quits. |
| `tierhop` or `tierhop serve` | Starts the proxy. |
| `tierhop --version` | Prints the installed version. |
| `tierhop --help` | Lists the commands, the options and the key variables. |

| Option | Applies to | Meaning |
| --- | --- | --- |
| `-c`, `--config PATH` | all but `init` | Config file. Default: `./tierhop.config.json` if it exists. |
| `-s`, `--system TEXT` | `chat` | System prompt. |
| `-m`, `--model NAME` | `chat` | Model, provider or alias. Default `auto`. |
| `-p`, `--port N` | `serve` | Port. Default: `$PORT`, else 4141. |
| `--host ADDR` | `serve` | Address to bind. Default: `$HOST`, else `127.0.0.1`. |
| `--api-key KEY` | `serve` | Key clients must send. Default: `$TIERHOP_API_KEY`, else none. |

`python -m tierhop` works the same way as `tierhop`.

The proxy serves:

| Route | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI-compatible chat completions. The response carries `x-tierhop-target` (the model that answered) and `x-tierhop-attempts`. |
| `GET /v1/models` | The names clients may use in the `model` field. |
| `GET /status` | Every model, whether it is benched, when it becomes available and its last error. |

## Configuration reference

`tierhop.config.json`, or the dictionary passed to `Router.create`:

| Key | Default | Meaning |
| --- | --- | --- |
| `order` | `groq, cerebras, gemini, mistral, openrouter, nvidia, huggingface, cohere, cloudflare` | Provider priority. Unlisted providers follow in the default order, then custom ones. |
| `strategy` | `priority` | `priority` always starts from the top. `round-robin` rotates the starting model. |
| `aliases` | none | Names for groups of providers or models. |
| `timeout` | `60` | Seconds an upstream may stay silent before it counts as failed. |
| `max_attempts` | `10` | Most upstream calls made for one request. |
| `providers.<name>.enabled` | `true` | Set to `false` to switch a provider off. |
| `providers.<name>.models` | discovered | Explicit model list in priority order. Skips discovery. |
| `providers.<name>.include` | see below | Regular expression a discovered model id must match. |
| `providers.<name>.exclude` | none | Regular expression that removes discovered model ids. |
| `providers.<name>.base_url` | built in | Endpoint of an OpenAI-compatible API. Required for providers that are not built in. |
| `providers.<name>.api_key_env` | built in | Name of the environment variable holding the key. |
| `providers.<name>.api_key` | none | The key itself. Prefer `api_key_env` so the key stays out of the file. |
| `providers.<name>.models_url` | `<base_url>/models` | Where the model listing lives, if it is somewhere else. |
| `providers.<name>.model_key` | `id` | The field of a listing entry that holds the model id. |

By default Gemini is limited to model ids containing `flash`, OpenRouter to ids ending in `:free`, and NVIDIA to its chat model families. Speech, embedding, image and moderation models are always skipped. Setting `include` or `exclude` for a provider replaces its default.

## Python reference

Everything is importable from `tierhop`.

| | |
| --- | --- |
| `Chat(system=None, *, model="auto", router=None, max_turns=20, **params)` | One conversation. `params` are sent with every request. |
| `chat.send(text)` | Returns the whole reply. |
| `chat.stream(text)` | Yields the reply piece by piece. |
| `await chat.asend(text)` | `send` for asyncio code. |
| `chat.reset()` | Forgets the conversation; the system prompt stays. |
| `chat.messages` | The history as a list of dictionaries. |
| `chat.last_target` | The `provider/model` that produced the latest reply. |
| `ask(prompt, system=None, **options)` | One question, no history. `options` are the same as for `Chat`. |
| `Router.create(config=None, **options)` | Builds a router from a config dictionary and the provider keys in the environment. |
| `router.chat(request)` | Sends an OpenAI-style request dictionary. Returns a result with `.response` (`.json()`, `.iter_chunks()`), `.target` and `.attempts`. |
| `router.complete(request)` | Like `chat`, but returns the parsed JSON. |
| `router.status()` | The state of every model. |
| `start(router=None, *, host="127.0.0.1", port=0, api_key=None, set_env=True)` | Runs the proxy in a background thread and returns its base URL. Port 0 picks a free port. With `set_env`, points the OpenAI SDK at it. |
| `stop()` | Stops the proxy that `start()` launched. |
| `create_server(router, host, port, api_key=None)` | The proxy as an `http.server` instance; call `serve_forever()` on it. |
| `ExhaustedError` | Raised when no model could answer. Has `retry_after`, `attempts` and `rejection`. |
| `StreamError` | Raised by `chat.stream` when a provider reports an error partway through a reply. |

`Chat` and `ask` share one router, built on first use from `./.env` and `./tierhop.config.json`. The router is synchronous and safe to share between threads.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| `No free models available` | No provider key was found. Run tierhop from the folder that holds your `.env`, or run `tierhop init` there. |
| `warning: <provider>: model discovery failed (the model listing returned 401)` | That provider's key is wrong or expired. Create a new one. Gemini reports a bad key as 400 instead of 401. |
| A Cloudflare token is set but Cloudflare never appears | `CLOUDFLARE_ACCOUNT_ID` is missing. Both values are needed. |
| Your bot still calls OpenAI after adding `tierhop.start()` | The client was created before `start()` ran, or it is given a `base_url` in code. Call `start()` first, or pass its return value as the base URL. |
| `All N free targets are rate limited or failing` | Every model is benched. The message says when to retry. Add keys for more providers, or a local model as the last fallback. |
| `Every target that was tried refused the request` | Two models rejected the request itself. The upstream error is included; common causes are a conversation that is too long (lower `max_turns`) or a parameter the model does not support. |
| Replies change in tone or quality from message to message | Different models are answering. Pin `models`, or request one provider with `model="groq"`. |
| The proxy answers 401 | It was started with a proxy key. Send that key as the OpenAI API key. |
| `error: cannot listen on 127.0.0.1:4141` | Something is already using that port, usually another tierhop. Stop it, or start this one with `--port 4142` and use that port in the base URL. |
| A model you expected is missing from `tierhop models` | It is filtered out. Check the provider's `include` and `exclude`, or list it under `models`. |
| A stream stops partway | The provider failed after it started answering. tierhop cannot switch models mid-reply; send the message again. |

To see what is happening, open `http://127.0.0.1:4141/status` while the proxy runs, or watch the proxy's terminal: it logs every upstream call and every model it benches.

## Limits

- Failover happens before the response starts. If a provider fails partway through a stream, the stream ends there.
- State is in memory. Restarting forgets which models are benched; the first requests rediscover it.
- Without a proxy key, anyone who can reach the proxy can spend your quota. It binds to `127.0.0.1` by default for that reason.
- tierhop uses one key per provider. It does not rotate multiple accounts to multiply a free quota, which most providers' terms prohibit.
- Different models answer different messages, so tone and quality can shift within one conversation.
- Free tiers change without notice. Treat this as a tool for prototypes, side projects and development, not for production traffic.

## Work on tierhop

```
git clone https://github.com/sakshamm21/tier-hop.git
cd tier-hop
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check . && mypy
```

The tests use a fake transport, so they need no API keys and no network. CI runs the same commands on Linux, Windows and macOS for Python 3.10 to 3.13.

| File | What it holds |
| --- | --- |
| [src/tierhop/router.py](src/tierhop/router.py) | The routing loop: which model to try, how each failure is judged, cooldown state |
| [src/tierhop/limits.py](src/tierhop/limits.py) | Reading rate-limit hints from response headers and error bodies |
| [src/tierhop/providers.py](src/tierhop/providers.py) | Built-in providers and model discovery |
| [src/tierhop/chat.py](src/tierhop/chat.py) | `Chat`, `ask` and the streaming text parser |
| [src/tierhop/server.py](src/tierhop/server.py) | The OpenAI-compatible proxy |
| [src/tierhop/cli.py](src/tierhop/cli.py) | The `tierhop` command |
| [src/tierhop/config.py](src/tierhop/config.py) | Loading `.env` and the config file |
| [src/tierhop/transport.py](src/tierhop/transport.py) | The HTTP client, and the interface tests replace |

[CONTRIBUTING.md](CONTRIBUTING.md) explains how a request flows through these files, how to add a built-in provider and what a change needs before it can be merged.

## Project

- **Contributing:** bug reports, provider requests and pull requests are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md); everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Security:** report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), which also explains how tierhop handles your keys.
- **Changes:** see [CHANGELOG.md](CHANGELOG.md). Versions follow semantic versioning; until 1.0, minor versions may change the API.

## License

[MIT](LICENSE)
