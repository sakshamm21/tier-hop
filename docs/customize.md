# Customize tierhop

[Back to the README](../README.md) · [Reference](reference.md)

All of this is optional. Settings go in a `tierhop.config.json` file in the folder you run tierhop from. Every key is listed in the [configuration reference](#configuration-reference) at the end.

## Give the bot a personality

The first argument to `Chat` is the system prompt. Extra arguments are sent with every request:

```python
chat = Chat(
    "You are Pixel, a cheerful support bot for a game studio. Answer in two sentences.",
    temperature=0.7,
    max_tokens=300,
)
```

In the terminal: `tierhop chat --system "You are Pixel, a cheerful support bot."`

## Choose which models answer

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

## Change which provider is tried first

```json
{ "order": ["gemini", "groq"] }
```

Providers you leave out follow in the default order. To switch one off, set `"enabled": false` for it under `providers`.

## Offer a fast bot and a smart bot

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

## Add another provider or a local model

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

## Spread requests across providers

By default every request starts from the top of the list, so the first provider takes all the traffic until it is rate limited. To rotate the starting point instead:

```json
{ "strategy": "round-robin" }
```

## Save and restore a conversation

`chat.messages` is a plain list of `{"role", "content"}` dictionaries:

```python
import json

with open("conversation.json", "w") as file:
    json.dump(chat.messages, file)

with open("conversation.json") as file:
    chat.messages = json.load(file)
```

`max_turns` (default 20) is the number of past exchanges sent with each request. Lower it if replies fail on long conversations; free models often have small limits.

## Configure from code instead of a file

`Router.create` takes the same keys as the config file. Pass the router to `Chat`:

```python
from tierhop import Chat, Router

router = Router.create(
    {"order": ["gemini", "groq"], "strategy": "round-robin"},
    on_attempt=print,  # called for every upstream call, including failed ones
)
chat = Chat("You are a helpful assistant.", router=router)
```

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
