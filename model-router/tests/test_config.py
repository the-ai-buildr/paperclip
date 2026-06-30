import os
from pathlib import Path

from app.config import load_settings


def test_resolve_role_and_passthrough(tmp_path, monkeypatch):
    roles = tmp_path / "roles.yaml"
    roles.write_text(
        "roles:\n"
        "  fast: anthropic/claude-sonnet-4\n"
        "  thinking:\n"
        "    model: anthropic/claude-opus-4\n"
        "    description: deep\n"
    )
    monkeypatch.setenv("ROLES_CONFIG_PATH", str(roles))
    monkeypatch.setenv("ROUTER_DEFAULT_ROLE", "fast")
    monkeypatch.delenv("MODEL_ROLE_FAST", raising=False)

    s = load_settings()

    # Known role -> upstream model.
    assert s.resolve("thinking") == "anthropic/claude-opus-4"
    # Empty -> default role -> its upstream model.
    assert s.resolve(None) == "anthropic/claude-sonnet-4"
    assert s.resolve("") == "anthropic/claude-sonnet-4"
    # Unknown -> passthrough unchanged (a real OpenRouter id still works).
    assert s.resolve("openai/gpt-4o") == "openai/gpt-4o"
    assert s.is_role("thinking") is True
    assert s.is_role("openai/gpt-4o") is False


def test_env_override_wins(tmp_path, monkeypatch):
    roles = tmp_path / "roles.yaml"
    roles.write_text("roles:\n  cheap: deepseek/deepseek-chat\n")
    monkeypatch.setenv("ROLES_CONFIG_PATH", str(roles))
    monkeypatch.setenv("MODEL_ROLE_CHEAP", "google/gemini-2.0-flash-001")

    s = load_settings()

    assert s.resolve("cheap") == "google/gemini-2.0-flash-001"


def test_env_underscore_aliases_hyphen_role(tmp_path, monkeypatch):
    roles = tmp_path / "roles.yaml"
    roles.write_text("roles:\n  ultra-thinking: anthropic/claude-opus-4\n")
    monkeypatch.setenv("ROLES_CONFIG_PATH", str(roles))
    # Shell env can't express a hyphen; underscore form must map to it.
    monkeypatch.setenv("MODEL_ROLE_ULTRA_THINKING", "deepseek/deepseek-r1")

    s = load_settings()

    assert s.resolve("ultra-thinking") == "deepseek/deepseek-r1"


def test_defaults_when_no_file(monkeypatch):
    monkeypatch.setenv("ROLES_CONFIG_PATH", "/nonexistent/roles.yaml")
    for k in list(os.environ):
        if k.startswith("MODEL_ROLE_"):
            monkeypatch.delenv(k, raising=False)

    s = load_settings()

    for role in ("fast", "coding", "thinking", "ultra-thinking", "research", "cheap"):
        assert role in s.roles, f"default role {role!r} missing"
    # Open-source-forward defaults for the lanes the user asked to cover.
    assert s.resolve("coding") == "qwen/qwen3-coder"
    assert s.resolve("thinking") == "deepseek/deepseek-r1"
    assert s.resolve("research") == "google/gemini-2.5-pro"


def test_auth_disabled_when_no_keys(monkeypatch):
    monkeypatch.setenv("ROLES_CONFIG_PATH", str(Path("roles.yaml")))
    monkeypatch.delenv("ROUTER_API_KEYS", raising=False)
    s = load_settings()
    assert s.auth_enabled is False
