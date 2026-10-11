# Reference

[Back to the README](../README.md) · [Customize tierhop](customize.md)

- [How it picks a model](#how-it-picks-a-model)
- [Commands](#commands)
- [Proxy routes](#proxy-routes)
- [Run the proxy on a server](#run-the-proxy-on-a-server)
- [Python API](#python-api)
- [Troubleshooting](#troubleshooting)

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

## Commands

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

`python -m tierhop` works the same way as `tierhop`. To run it without installing first, if you have [uv](https://docs.astral.sh/uv/):

```
uvx --from git+https://github.com/sakshamm21/tier-hop.git tierhop
```

## Proxy routes

| Route | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI-compatible chat completions. The response carries `x-tierhop-target` (the model that answered) and `x-tierhop-attempts`. |
| `GET /v1/models` | The names clients may use in the `model` field. |
| `GET /status` | Every model, whether it is benched, when it becomes available and its last error. |

Streaming, tool calls and other request fields are passed through unchanged. Browsers can call the proxy directly; [examples/web_chatbot.html](../examples/web_chatbot.html) is a chat page that does. Only chat completions are proxied.

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

## Python API

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

For a library that wants the base URL passed in, use what `start()` returns:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(base_url=tierhop.start(), api_key="unused", model="auto")
```

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
