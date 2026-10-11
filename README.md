# tierhop

[![CI](https://github.com/sakshamm21/tier-hop/actions/workflows/ci.yml/badge.svg)](https://github.com/sakshamm21/tier-hop/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Build chatbots and other LLM features on free models, without babysitting rate limits.

tierhop puts the free tiers of nine LLM providers behind one OpenAI-compatible interface. When a model hits its rate limit or runs out of quota, the next request goes to another model, and the first one is used again once its limit resets.

```
your app  ──►  tierhop  ──►  Groq          rate limited, benched 42s
                        ──►  Cerebras      ok
                             Gemini
                             Mistral
                             OpenRouter, NVIDIA, Hugging Face, Cohere, Cloudflare
```

- Plugs into a chatbot you already have: two lines in Python, or one environment variable in any language.
- Works with the OpenAI SDK and anything else that speaks the OpenAI API.
- Finds the currently available free models itself, so there is no model list to maintain.
- Has no dependencies outside the Python standard library.
- Runs on your machine with your own free API keys, which are sent only to the provider they belong to.

## Install

Requires Python 3.10 or newer.

```
pip install git+https://github.com/sakshamm21/tier-hop.git
```

The repository is named `tier-hop`; the package you import and the command you run are both `tierhop`.

## Quick start

```
tierhop init     # creates .env; paste in at least one free API key
tierhop check    # tests each key with one small request
tierhop chat     # opens a chatbot in your terminal
```

One key is enough; more providers means more free quota to fall back on. Keys set as environment variables work too, and take priority over the file. If the terminal chatbot works, tierhop will work in your own project.

## Use it in your chatbot

### A Python bot that uses the OpenAI SDK

Add two lines above the code you already have:

```python
import tierhop

tierhop.start()

from openai import OpenAI

client = OpenAI()  # now answers from the free models
```

`start()` runs tierhop inside your bot's process and points the OpenAI SDK at it, so call it before you create the client. Streaming, tool calls and the async client all work, and your existing model name can stay. It returns the address it listens on, for libraries that want a base URL passed in, such as LangChain.

### A bot in any other language, or a tool you can only configure

Start the proxy and leave it running:

```
tierhop
```

Then give your bot or tool these settings. The official OpenAI SDKs read the first two from the environment as `OPENAI_BASE_URL` and `OPENAI_API_KEY`, so the code does not change.

| Setting | Value |
| --- | --- |
| Base URL | `http://127.0.0.1:4141/v1` |
| API key | any text |
| Model | `auto`, or leave the name you have |

### A new Python bot

`Chat` keeps the conversation history for you:

```python
from tierhop import Chat

chat = Chat("You are a helpful assistant.")

print(chat.send("Hi, my name is Sam."))
print(chat.send("What is my name?"))  # it remembers

for piece in chat.stream("Tell me a short story."):
    print(piece, end="", flush=True)
```

For Discord, Telegram or Slack bots, keep one `Chat` per user and call `await chat.asend(text)` so one user's reply does not block the others. For tasks with no conversation, such as classifying or summarizing, use `ask(prompt, system=...)`.

When every free model is rate limited, these raise `ExhaustedError`, whose `retry_after` is the number of seconds until a model is available again.

## Free providers

Each provider is switched on by putting its key in `.env`. The ones you leave empty are skipped.

| Provider | Variable in `.env` | Create a key at | Good to know |
| --- | --- | --- | --- |
| Groq | `GROQ_API_KEY` | https://console.groq.com/keys | Very fast responses |
| Cerebras | `CEREBRAS_API_KEY` | https://cloud.cerebras.ai | Very fast responses |
| Google Gemini | `GEMINI_API_KEY` | https://aistudio.google.com/apikey | Only the Flash models are used by default |
| Mistral | `MISTRAL_API_KEY` | https://console.mistral.ai/api-keys | The free plan lets Mistral train on your requests |
| OpenRouter | `OPENROUTER_API_KEY` | https://openrouter.ai/keys | Only models ending in `:free` are used |
| NVIDIA | `NVIDIA_API_KEY` | https://build.nvidia.com/settings/api-keys | Large catalog of models |
| Hugging Face | `HF_TOKEN` | https://huggingface.co/settings/tokens | A small monthly credit, not a rate limit |
| Cohere | `COHERE_API_KEY` | https://dashboard.cohere.com/api-keys | Trial keys are for non-commercial use |
| Cloudflare Workers AI | `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` | https://dash.cloudflare.com/profile/api-tokens | Needs both values |

Free limits change often, so they are not listed here. tierhop does not need to know them: it reacts to what each provider reports. Any other OpenAI-compatible service, or a local model such as Ollama, can be added with [a few lines of config](docs/customize.md#add-another-provider-or-a-local-model).

## Documentation

| | |
| --- | --- |
| [Customize tierhop](docs/customize.md) | Pick models, reorder providers, define aliases such as `fast` and `smart`, add providers or a local model, and every config key |
| [Reference](docs/reference.md) | How a model is picked, commands, proxy routes, running on a server, the Python API and troubleshooting |
| [examples/](examples/) | Runnable chatbots: terminal, multi-user, OpenAI SDK, an existing OpenAI bot, one-off tasks and a web page |

## Limits

- Failover happens before a response starts. If a provider fails partway through a stream, the stream ends there.
- Different models answer different messages, so tone and quality can shift within one conversation. Pin the models you want to avoid that.
- State is in memory. Restarting forgets which models are benched.
- Without a proxy key, anyone who can reach the proxy can spend your quota, so it listens on `127.0.0.1` by default.
- tierhop uses one key per provider. It does not rotate several accounts to multiply a free quota, which most providers' terms prohibit.
- Free tiers change without notice. Use this for prototypes, side projects and development, not for production traffic.

## Contributing

```
git clone https://github.com/sakshamm21/tier-hop.git
cd tier-hop
pip install -e ".[dev]"
pytest
```

The tests need no API keys and no network. [CONTRIBUTING.md](CONTRIBUTING.md) explains how the code is laid out and how to add a provider. Report security problems privately as described in [SECURITY.md](SECURITY.md). Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
