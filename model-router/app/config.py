"""Configuration loading for the model router.

The router maps logical *roles* (a model "type" such as ``thinking``, ``fast``,
or ``cheap``) to concrete upstream model IDs on OpenRouter. Roles are defined in
``roles.yaml`` and can be overridden per-role with environment variables, so an
operator can retune the mapping without editing code or rebuilding the image.

Environment variables
----------------------
OPENROUTER_API_KEY      Upstream OpenRouter key (required at request time).
OPENROUTER_BASE_URL     Upstream base URL. Default: https://openrouter.ai/api/v1
ROUTER_API_KEYS         Comma-separated keys clients must present as
                        ``Authorization: Bearer <key>``. Empty = auth disabled.
ROUTER_DEFAULT_ROLE     Role used when a request omits ``model``. Default: fast
ROLES_CONFIG_PATH       Path to the roles YAML file. Default: ./roles.yaml
MODEL_ROLE_<NAME>       Override (or define) the upstream model for role <NAME>,
                        e.g. MODEL_ROLE_THINKING=anthropic/claude-opus-4.
OPENROUTER_HTTP_REFERER Optional value sent as the OpenRouter HTTP-Referer header.
OPENROUTER_X_TITLE      Optional value sent as the OpenRouter X-Title header.
REQUEST_TIMEOUT_SECONDS Upstream request timeout. Default: 600
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_ROLES: dict[str, str] = {
    # Day-to-day coding — balanced, low latency (the default role).
    "fast": "anthropic/claude-sonnet-4",
    # Open-weight Qwen3 Coder for code generation / edits.
    "coding": "qwen/qwen3-coder",
    # Open-weight DeepSeek-R1 for step-by-step reasoning / planning.
    "thinking": "deepseek/deepseek-r1",
    # Top-tier reasoning for the hardest problems.
    "ultra-thinking": "anthropic/claude-opus-4",
    # Long-context research / synthesis.
    "research": "google/gemini-2.5-pro",
    # High-volume, low-stakes calls (commit messages, classification, etc.).
    "cheap": "deepseek/deepseek-chat",
}

DEFAULT_ROLE_DESCRIPTIONS: dict[str, str] = {
    "fast": "Balanced coding model for everyday work",
    "coding": "Open-weight coding model (Qwen3 Coder)",
    "thinking": "Open-weight reasoning model (DeepSeek-R1)",
    "ultra-thinking": "Top-tier reasoning for the hardest work",
    "research": "Long-context research / synthesis model",
    "cheap": "Low-cost model for high-volume, low-stakes calls",
}

_ENV_ROLE_PREFIX = "MODEL_ROLE_"


@dataclass
class Settings:
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    router_api_keys: set[str] = field(default_factory=set)
    default_role: str = "fast"
    roles: dict[str, str] = field(default_factory=dict)
    role_descriptions: dict[str, str] = field(default_factory=dict)
    http_referer: str = ""
    x_title: str = "Paperclip Model Router"
    request_timeout_seconds: float = 600.0

    @property
    def auth_enabled(self) -> bool:
        return len(self.router_api_keys) > 0

    def resolve(self, model: str | None) -> str:
        """Resolve a requested ``model`` to a concrete upstream model ID.

        Resolution order:
        1. Empty/None -> the default role.
        2. A known role name -> its configured upstream model.
        3. Anything else -> passed through unchanged, so callers can still
           request a full OpenRouter model ID directly.
        """
        name = (model or "").strip()
        if not name:
            name = self.default_role
        return self.roles.get(name, name)

    def is_role(self, model: str | None) -> bool:
        return (model or "").strip() in self.roles


def _load_roles_file(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Load roles + descriptions from a YAML file.

    Supports two shapes per entry::

        roles:
          fast: anthropic/claude-sonnet-4          # shorthand
          thinking:                                 # expanded
            model: anthropic/claude-opus-4
            description: Deep reasoning model
    """
    if not path.exists():
        return dict(DEFAULT_ROLES), dict(DEFAULT_ROLE_DESCRIPTIONS)

    data = yaml.safe_load(path.read_text()) or {}
    raw = data.get("roles", data) if isinstance(data, dict) else {}
    models: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict):
                model = str(value.get("model", "")).strip()
                if model:
                    models[name] = model
                desc = value.get("description")
                if desc:
                    descriptions[name] = str(desc)
            elif value:
                models[name] = str(value).strip()
    return models, descriptions


def load_settings() -> Settings:
    roles_path = Path(os.environ.get("ROLES_CONFIG_PATH", "roles.yaml"))
    roles, descriptions = _load_roles_file(roles_path)

    # Per-role env overrides, e.g. MODEL_ROLE_CODING=qwen/qwen3-coder.
    # Shell env names can't contain hyphens, so also register an underscore ->
    # hyphen alias: MODEL_ROLE_ULTRA_THINKING overrides the "ultra-thinking" role.
    for key, value in os.environ.items():
        if key.startswith(_ENV_ROLE_PREFIX) and value.strip():
            role_name = key[len(_ENV_ROLE_PREFIX) :].lower()
            roles[role_name] = value.strip()
            if "_" in role_name:
                roles[role_name.replace("_", "-")] = value.strip()

    api_keys = {
        k.strip()
        for k in os.environ.get("ROUTER_API_KEYS", "").split(",")
        if k.strip()
    }

    default_role = os.environ.get("ROUTER_DEFAULT_ROLE", "fast").strip() or "fast"

    return Settings(
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
        openrouter_base_url=os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        router_api_keys=api_keys,
        default_role=default_role,
        roles=roles,
        role_descriptions=descriptions,
        http_referer=os.environ.get("OPENROUTER_HTTP_REFERER", "").strip(),
        x_title=os.environ.get("OPENROUTER_X_TITLE", "Paperclip Model Router").strip(),
        request_timeout_seconds=float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "600")),
    )
