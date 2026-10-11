# Changelog

Notable changes to tierhop are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-11

### Added

- `Router`, which sends each request to the first available free model and moves on
  when one is rate limited, out of quota or failing. Cooldowns come from the
  rate-limit hints each provider returns.
- Live model discovery for nine built-in providers: Groq, Cerebras, Google Gemini,
  Mistral, OpenRouter, NVIDIA, Hugging Face, Cohere and Cloudflare Workers AI.
- Custom providers through `tierhop.config.json`, for any OpenAI-compatible endpoint.
- An OpenAI-compatible proxy with streaming, an optional proxy key and a `/status` route.
- `tierhop.start()`, which runs the proxy inside an existing Python process and points
  the OpenAI SDK at it.
- `Chat`, a conversation with history, streaming and an asyncio `asend`, and `ask()`
  for one-off tasks.
- The `tierhop` command with `init`, `check`, `models`, `chat` and `serve`.
- `.env` files saved with a byte-order mark, as Notepad and PowerShell write them, are
  read correctly.
- The proxy refuses to start on a port that is already in use, on Windows as well, and
  says how to pick another one.

[Unreleased]: https://github.com/sakshamm21/tier-hop/commits/main
[0.1.0]: https://github.com/sakshamm21/tier-hop/commits/main
