"""Which providers are available and which models each one serves."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .transport import Transport


@dataclass(frozen=True)
class Preset:
    base_url: str
    """May contain {ENV_VAR} placeholders, filled in from the environment."""
    api_key_env: str
    keys_url: str
    """Where to create a free API key."""
    include: str | None = None
    """Only discovered model ids matching this are used."""
    exclude: str | None = None
    models_url: str | None = None
    """Where the model listing lives, when it is not at {base_url}/models."""
    model_key: str = "id"
    """The field of a listing entry that holds the model id."""

    @property
    def env_vars(self) -> list[str]:
        """Every environment variable this provider needs."""
        return [self.api_key_env, *_PLACEHOLDER.findall(self.base_url)]


_PLACEHOLDER = re.compile(r"\{([A-Z0-9_]+)\}")

# Providers with a recurring free tier and an OpenAI-compatible chat API.
PRESETS: dict[str, Preset] = {
    "groq": Preset(
        "https://api.groq.com/openai/v1", "GROQ_API_KEY", "https://console.groq.com/keys"
    ),
    "cerebras": Preset(
        "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "https://cloud.cerebras.ai"
    ),
    "gemini": Preset(
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "https://aistudio.google.com/apikey",
        include="flash",
    ),
    "mistral": Preset(
        "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "https://console.mistral.ai/api-keys"
    ),
    "openrouter": Preset(
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/keys",
        include=":free$",
    ),
    "nvidia": Preset(
        "https://integrate.api.nvidia.com/v1",
        "NVIDIA_API_KEY",
        "https://build.nvidia.com/settings/api-keys",
        # The listing mixes chat models with retrieval, vision and tooling models.
        include="instruct|nemotron|kimi|glm|gpt-oss|gemma-[3-9]|deepseek-v|mistral-large|palmyra",
        exclude="reward|parse|vlm|topic-control|translate|code|vision|chatqa",
    ),
    "huggingface": Preset(
        "https://router.huggingface.co/v1", "HF_TOKEN", "https://huggingface.co/settings/tokens"
    ),
    "cohere": Preset(
        "https://api.cohere.ai/compatibility/v1",
        "COHERE_API_KEY",
        "https://dashboard.cohere.com/api-keys",
        models_url="https://api.cohere.com/v1/models?endpoint=chat&page_size=1000",
        model_key="name",
    ),
    "cloudflare": Preset(
        "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        "CLOUDFLARE_API_TOKEN",
        "https://dash.cloudflare.com/profile/api-tokens",
        include="^@",
        models_url="https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
        "/ai/models/search?task=Text%20Generation&per_page=100",
        model_key="name",
    ),
}

DEFAULT_ORDER = [
    "groq",
    "cerebras",
    "gemini",
    "mistral",
    "openrouter",
    "nvidia",
    "huggingface",
    "cohere",
    "cloudflare",
]


def setup_help() -> str:
    """Lists the environment variables tierhop looks for and where to get each key."""
    lines = []
    for name in DEFAULT_ORDER:
        preset = PRESETS[name]
        lines.append(f"  {preset.api_key_env:<22}{preset.keys_url}")
        lines += [f"  {extra:<22}(needed with the line above)" for extra in preset.env_vars[1:]]
    return "\n".join(lines)


# Model listings also contain speech, embedding, image and moderation models.
_NOT_CHAT = re.compile(
    r"whisper|tts|speech|audio|transcri|embed|rerank|guard|safety|moderation|ocr|image|imagen|veo|lyria",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str | None = None
    models: tuple[str, ...] | None = None
    include: re.Pattern[str] | None = None
    exclude: re.Pattern[str] | None = None
    models_url: str | None = None
    model_key: str = "id"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}


@dataclass(frozen=True)
class Target:
    provider: Provider
    model: str

    @property
    def id(self) -> str:
        return f"{self.provider.name}/{self.model}"


def _fill(url: str | None, env: Mapping[str, str]) -> str | None:
    """Fills {ENV_VAR} placeholders. Returns None if the url or any variable is missing."""
    if not url:
        return None
    if any(not env.get(name) for name in _PLACEHOLDER.findall(url)):
        return None
    return _PLACEHOLDER.sub(lambda match: env[match.group(1)], url)


def resolve_providers(config: Mapping[str, Any], env: Mapping[str, str]) -> list[Provider]:
    """Presets become active when their API key is set; custom providers need a base_url."""
    configured: Mapping[str, Mapping[str, Any]] = config.get("providers") or {}
    names = dict.fromkeys([*(config.get("order") or []), *DEFAULT_ORDER, *configured])
    providers = []
    for name in names:
        preset = PRESETS.get(name)
        custom = configured.get(name) or {}
        if custom.get("enabled") is False:
            continue
        base_url = _fill(custom.get("base_url") or (preset.base_url if preset else None), env)
        if not base_url:
            continue
        key_env = custom.get("api_key_env") or (preset.api_key_env if preset else None)
        api_key = custom.get("api_key") or (env.get(key_env) if key_env else None)
        if not api_key and not custom.get("base_url"):
            continue
        include = custom.get("include") or (preset.include if preset else None)
        exclude = custom.get("exclude") or (preset.exclude if preset else None)
        models_url = custom.get("models_url") or (preset.models_url if preset else None)
        providers.append(
            Provider(
                name=name,
                base_url=base_url.rstrip("/"),
                api_key=api_key or None,
                models=tuple(custom["models"]) if custom.get("models") else None,
                include=re.compile(include, re.IGNORECASE) if include else None,
                exclude=re.compile(exclude, re.IGNORECASE) if exclude else None,
                models_url=_fill(models_url, env),
                model_key=custom.get("model_key") or (preset.model_key if preset else "id"),
            )
        )
    return providers


def discover_models(provider: Provider, transport: Transport) -> list[str]:
    """Asks the provider which models it currently serves."""
    url = provider.models_url or f"{provider.base_url}/models"
    response = transport("GET", url, provider.auth_headers(), None, 15.0)
    if not response.ok:
        response.close()
        raise OSError(f"the model listing returned {response.status}")
    listing = response.json()
    entries: Any = listing
    if isinstance(listing, dict):
        # OpenAI-style listings use "data"; Cohere uses "models" and Cloudflare "result".
        entries = next((listing[k] for k in ("data", "models", "result") if k in listing), [])
    ids: dict[str, None] = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("is_deprecated") is True:
            continue
        model = entry.get(provider.model_key)
        if not isinstance(model, str):
            continue
        model = model.removeprefix("models/")
        if not model or _NOT_CHAT.search(model):
            continue
        if provider.include and not provider.include.search(model):
            continue
        if provider.exclude and provider.exclude.search(model):
            continue
        ids[model] = None
    return list(ids)


def resolve_targets(
    providers: list[Provider],
    transport: Transport,
    warn: Callable[[str], None] = lambda message: None,
) -> list[Target]:
    def models_of(provider: Provider) -> list[str]:
        if provider.models is not None:
            return list(provider.models)
        try:
            models = discover_models(provider, transport)
        except (OSError, ValueError) as err:
            warn(f"{provider.name}: model discovery failed ({err})")
            return []
        if not models:
            warn(f"{provider.name}: no usable models found")
        return models

    if not providers:
        return []
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        listings = list(pool.map(models_of, providers))
    return [
        Target(provider, model)
        for provider, models in zip(providers, listings, strict=True)
        for model in models
    ]
