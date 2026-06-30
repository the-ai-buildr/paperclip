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


def test_defaults_when_no_file(monkeypatch):
    monkeypatch.setenv("ROLES_CONFIG_PATH", "/nonexistent/roles.yaml")
    for k in list(os.environ):
        if k.startswith("MODEL_ROLE_"):
            monkeypatch.delenv(k, raising=False)

    s = load_settings()

    assert "thinking" in s.roles
    assert "fast" in s.roles
    assert "cheap" in s.roles


def test_auth_disabled_when_no_keys(monkeypatch):
    monkeypatch.setenv("ROLES_CONFIG_PATH", str(Path("roles.yaml")))
    monkeypatch.delenv("ROUTER_API_KEYS", raising=False)
    s = load_settings()
    assert s.auth_enabled is False
