import json

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_upstream():
    """Capture the request body forwarded upstream and return a canned reply."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "model": captured["body"].get("model"),
            },
        )

    return handler, captured


def make_client(monkeypatch, mock_upstream, **env):
    roles = "roles.yaml"
    monkeypatch.setenv("ROLES_CONFIG_PATH", roles)
    monkeypatch.setenv("OPENROUTER_API_KEY", env.pop("OPENROUTER_API_KEY", "sk-or-test"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    from app.main import app

    client = TestClient(app)
    client.__enter__()  # run lifespan so app.state is populated
    # Swap the upstream client for one backed by our mock transport.
    handler, _ = mock_upstream
    app.state.client = httpx.AsyncClient(
        base_url=app.state.settings.openrouter_base_url,
        transport=httpx.MockTransport(handler),
    )
    return app, client


def test_healthz(monkeypatch, mock_upstream):
    _, client = make_client(monkeypatch, mock_upstream)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "fast" in body["roles"]
    client.__exit__(None, None, None)


def test_list_models(monkeypatch, mock_upstream):
    _, client = make_client(monkeypatch, mock_upstream)
    r = client.get("/v1/models")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["data"]}
    assert {"fast", "thinking", "cheap"}.issubset(ids)
    client.__exit__(None, None, None)


def test_chat_completions_resolves_role(monkeypatch, mock_upstream):
    _, captured = mock_upstream
    _, client = make_client(monkeypatch, mock_upstream)
    r = client.post(
        "/v1/chat/completions",
        json={"model": "thinking", "messages": [{"role": "user", "content": "hey"}]},
    )
    assert r.status_code == 200
    # The role "thinking" was rewritten to the upstream model before forwarding.
    assert captured["body"]["model"] == "anthropic/claude-opus-4"
    assert captured["auth"] == "Bearer sk-or-test"
    client.__exit__(None, None, None)


def test_chat_completions_passthrough_unknown_model(monkeypatch, mock_upstream):
    _, captured = mock_upstream
    _, client = make_client(monkeypatch, mock_upstream)
    r = client.post(
        "/v1/chat/completions",
        json={"model": "openai/gpt-4o", "messages": []},
    )
    assert r.status_code == 200
    assert captured["body"]["model"] == "openai/gpt-4o"
    client.__exit__(None, None, None)


def test_default_role_when_model_omitted(monkeypatch, mock_upstream):
    _, captured = mock_upstream
    _, client = make_client(monkeypatch, mock_upstream, ROUTER_DEFAULT_ROLE="cheap")
    r = client.post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 200
    assert captured["body"]["model"] == "deepseek/deepseek-chat"
    client.__exit__(None, None, None)


def test_auth_required_when_keys_set(monkeypatch, mock_upstream):
    _, client = make_client(monkeypatch, mock_upstream, ROUTER_API_KEYS="secret1,secret2")
    # No token -> 401
    r = client.post("/v1/chat/completions", json={"model": "fast", "messages": []})
    assert r.status_code == 401
    # Valid token -> 200
    r = client.post(
        "/v1/chat/completions",
        json={"model": "fast", "messages": []},
        headers={"Authorization": "Bearer secret2"},
    )
    assert r.status_code == 200
    client.__exit__(None, None, None)
