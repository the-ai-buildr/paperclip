# Paperclip Model Router

A small **FastAPI** service that sits in front of [OpenRouter](https://openrouter.ai)
and exposes your models by **role** (a logical "model type") instead of by a
hard-coded model ID.

Request `thinking`, `fast`, or `cheap` — the router rewrites that to whatever
OpenRouter model you've mapped the role to and forwards the call. It speaks the
**OpenAI Chat Completions API**, so any OpenAI-compatible client (OpenCode, the
OpenAI SDKs, `curl`) can use it unchanged.

```
OpenCode (or any OpenAI client)
        │  POST /v1/chat/completions  { "model": "thinking", ... }
        ▼
┌─────────────────────────┐   resolve role → upstream model
│  Paperclip Model Router  │   thinking → anthropic/claude-opus-4
│  (FastAPI, this service) │   fast     → anthropic/claude-sonnet-4
└─────────────────────────┘   cheap    → deepseek/deepseek-chat
        │  POST /chat/completions  { "model": "anthropic/claude-opus-4", ... }
        ▼
   OpenRouter  ──►  the actual model
```

**Why a router?** Coding agents pick a model by ID. Addressing a *role* instead
lets you retune which concrete model backs "fast" vs "thinking" vs "cheap" in
one place — no agent reconfiguration, no redeploys of the agent.

## Endpoints

| Method | Path                   | Purpose                                              |
| ------ | ---------------------- | ---------------------------------------------------- |
| `GET`  | `/healthz`             | Liveness + which roles are loaded.                   |
| `GET`  | `/v1/models`           | Lists roles as OpenAI model objects (for discovery). |
| `POST` | `/v1/chat/completions` | OpenAI chat completions; supports `stream: true`.    |
| `POST` | `/v1/completions`      | Legacy text completions passthrough.                 |

Unknown model names pass through **unchanged**, so you can still request a full
OpenRouter ID (e.g. `openai/gpt-4o`) directly through the same endpoint.

## Quickstart (local)

```bash
cd model-router
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then put your real OPENROUTER_API_KEY in .env
set -a; . ./.env; set +a       # export the vars into the shell

uvicorn app.main:app --host 0.0.0.0 --port 8787
```

Smoke test it:

```bash
curl -s localhost:8787/healthz | jq
curl -s localhost:8787/v1/models | jq '.data[].id'

curl -s localhost:8787/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"fast","messages":[{"role":"user","content":"say hi"}]}' | jq
```

## Run with Docker

```bash
docker build -t paperclip-model-router model-router
docker run --rm -p 8787:8787 \
  -e OPENROUTER_API_KEY=sk-or-... \
  paperclip-model-router
```

## Configuration

All config is environment-driven (see [`.env.example`](.env.example)):

| Variable                  | Default                        | Description                                                       |
| ------------------------- | ------------------------------ | ----------------------------------------------------------------- |
| `OPENROUTER_API_KEY`      | —                              | **Required.** Your OpenRouter key.                                |
| `OPENROUTER_BASE_URL`     | `https://openrouter.ai/api/v1` | Upstream base URL.                                                |
| `ROUTER_API_KEYS`         | *(empty)*                      | Comma-separated client keys. Empty disables auth (localhost-ok).  |
| `ROUTER_DEFAULT_ROLE`     | `fast`                         | Role used when a request omits `model`.                           |
| `ROLES_CONFIG_PATH`       | `roles.yaml`                   | Path to the role definitions file.                                |
| `MODEL_ROLE_<NAME>`       | —                              | Override/define a role's upstream model, e.g. `MODEL_ROLE_FAST`.  |
| `OPENROUTER_HTTP_REFERER` | *(empty)*                      | Optional OpenRouter attribution header.                           |
| `OPENROUTER_X_TITLE`      | `Paperclip Model Router`       | Optional OpenRouter attribution header.                           |
| `REQUEST_TIMEOUT_SECONDS` | `600`                          | Upstream request timeout.                                         |

### Defining roles

Edit [`roles.yaml`](roles.yaml). Both shapes are supported:

```yaml
roles:
  fast: anthropic/claude-sonnet-4          # shorthand
  thinking:                                 # expanded
    model: anthropic/claude-opus-4
    description: Deep reasoning model
```

Or override a single role without touching the file:

```bash
MODEL_ROLE_THINKING=anthropic/claude-opus-4
MODEL_ROLE_CHEAP=google/gemini-2.0-flash-001
```

> The default model IDs are sensible starting points. Browse
> [openrouter.ai/models](https://openrouter.ai/models) and pick the exact
> IDs/price points you want, then update `roles.yaml` or the env overrides.

## Using it from OpenCode

OpenCode supports OpenAI-compatible custom providers. Point a provider at this
router and use the role names as model IDs. See the full walkthrough in
[`../doc/plans/2026-06-30-opencode-openrouter-model-router.md`](../doc/plans/2026-06-30-opencode-openrouter-model-router.md).

```jsonc
// ~/.config/opencode/opencode.json (or opencode.jsonc)
{
  "provider": {
    "paperclip-router": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://localhost:8787/v1",
        "apiKey": "{env:ROUTER_API_KEY}"   // only needed if ROUTER_API_KEYS is set
      },
      "models": {
        "thinking": { "name": "Thinking (router)" },
        "fast":     { "name": "Fast (router)" },
        "cheap":    { "name": "Cheap (router)" }
      }
    }
  }
}
```

Then select `paperclip-router/thinking` (or `/fast`, `/cheap`) in OpenCode.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests mock the OpenRouter upstream with `httpx.MockTransport`, so they run
offline and assert that role resolution + auth behave correctly.
