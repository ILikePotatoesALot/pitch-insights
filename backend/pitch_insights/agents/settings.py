"""Agent settings, read from the environment and the repo's .env file.

Keys stay in .env (ignored by git) or real environment variables; nothing here logs them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
PROVIDERS = ("foundry", "github", "foundry_local")


@dataclass(frozen=True)
class AgentSettings:
    provider: str = "foundry"
    endpoint: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    embedding_model: str = ""
    timeout_s: float = 20.0      # per model call, before the SDK's own retries
    max_retries: int = 2         # the OpenAI SDK's retry layer (backoff, honours Retry-After); the only one
    max_tokens: int = 220        # rate limits count max_tokens, so keep it near the real output size
    temperature: float = 0.4
    concurrency: int = 3         # model calls in flight at once, to avoid bursts that trip rate limits

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)


def _num(env: dict, key: str, default, cast, lo, hi):
    """A number from the environment, or the default if it's missing, malformed or outside lo..hi."""
    try:
        value = cast(env[key]) if env.get(key) else default
    except ValueError:
        return default
    return value if lo <= value <= hi else default


def load_settings(env_file: Path | None = ENV_FILE) -> AgentSettings:
    """Real environment variables win over the .env file."""
    env = {k: v for k, v in (dotenv_values(env_file) if env_file and env_file.exists() else {}).items() if v}
    env.update({k: v for k, v in os.environ.items() if v})
    provider = env.get("LLM_PROVIDER", "foundry").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, not {provider!r}")
    if provider == "foundry":
        endpoint, key = env.get("AZURE_OPENAI_ENDPOINT", ""), env.get("AZURE_OPENAI_API_KEY", "")
        model = env.get("AZURE_OPENAI_DEPLOYMENT", "")
    elif provider == "github":
        endpoint = env.get("GITHUB_MODELS_ENDPOINT", "https://models.github.ai/inference")
        key, model = env.get("GITHUB_TOKEN", ""), env.get("GITHUB_MODEL", "openai/gpt-4o")
    else:
        endpoint = env.get("FOUNDRY_LOCAL_ENDPOINT", "http://localhost:5272/v1")
        key, model = "foundry-local", env.get("FOUNDRY_LOCAL_MODEL", "")
    return AgentSettings(
        provider=provider, endpoint=endpoint, api_key=key, model=model,
        embedding_model=env.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""),
        timeout_s=_num(env, "AGENT_TIMEOUT_S", 20.0, float, 1, 300),
        max_retries=_num(env, "AGENT_MAX_RETRIES", 2, int, 0, 10),
        max_tokens=_num(env, "AGENT_MAX_TOKENS", 220, int, 16, 4096),
        temperature=_num(env, "AGENT_TEMPERATURE", 0.4, float, 0, 2),
        concurrency=_num(env, "AGENT_CONCURRENCY", 3, int, 1, 32),
    )
