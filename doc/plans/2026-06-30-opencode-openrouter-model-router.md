# Plan & Setup Guide: OpenCode + OpenRouter via a Role-Based Model Router

**Date:** 2026-06-30
**Status:** Implemented (router service) + setup guide
**Owner:** tyhunt82
**Branch:** `claude/paperclip-fastapi-router-ypdv46`

## Goal

Use **OpenCode** as a coding agent for building Paperclip ("PC"), driven by
**OpenRouter** models, addressed by **role** rather than by a hard-coded model
ID. A small **FastAPI router** sits between OpenCode and OpenRouter and maps
logical roles — `fast`, `coding`, `thinking`, `ultra-thinking`, `research`,
`cheap` — to concrete OpenRouter models (open-source-forward by default).

You ask for a *model type*; the router decides *which model* serves it. Retune
the mapping in one place and every client follows, with no agent reconfig.

## Why this shape

- **OpenCode** is an open-source terminal coding agent that talks to any
  OpenAI-compatible endpoint via custom providers. That makes it a clean fit as
  a "code agent" you point at your own gateway.
- **OpenRouter** gives one API key and one OpenAI-compatible surface across many
  model vendors (Anthropic, OpenAI, DeepSeek, Google, …).
- A **role router** decouples *intent* ("I want the coding model") from
  *selection* ("…which today is `qwen/qwen3-coder`"). You change the backing
  model centrally; agents, scripts, and teammates keep using `coding`.

```
┌──────────┐   model:"coding"     ┌──────────────────────┐  model:"qwen/        ┌────────────┐
│ OpenCode │ ───────────────────▶ │ Paperclip Model      │  qwen3-coder"        │ OpenRouter │ ─▶ model
│ (agent)  │   OpenAI /v1 schema  │ Router (FastAPI)     │ ───────────────────▶ │            │
└──────────┘                      │ role → upstream model│   OpenAI /v1 schema  └────────────┘
                                  └──────────────────────┘
```

## What was built (in this branch)

A self-contained FastAPI service under [`/model-router`](../../model-router):

```
model-router/
  app/
    __init__.py
    config.py      # role → model resolution (roles.yaml + MODEL_ROLE_* env overrides)
    upstream.py    # OpenRouter HTTP client + headers
    main.py        # FastAPI app: /healthz, /v1/models, /v1/chat/completions, /v1/completions
  roles.yaml       # default role map (fast / coding / thinking / ultra-thinking / research / cheap)
  tests/           # pytest: role resolution, passthrough, auth, model listing
  requirements.txt requirements-dev.txt
  Dockerfile  .dockerignore  .env.example  README.md
```

Behavior:

- **OpenAI-compatible.** `POST /v1/chat/completions` accepts the standard body,
  honors `stream: true` (relays the SSE byte stream), and returns OpenRouter's
  response unchanged.
- **Role resolution.** `model` is matched against `roles.yaml`. A known role is
  rewritten to its upstream model; an unknown value passes through untouched, so
  you can still request a full OpenRouter ID (`openai/gpt-4o`) directly.
- **Default role.** A request with no `model` uses `ROUTER_DEFAULT_ROLE`
  (`fast` by default).
- **Discovery.** `GET /v1/models` lists the roles as OpenAI model objects, so
  OpenCode (and other clients) can enumerate them.
- **Optional auth.** Set `ROUTER_API_KEYS` to require a client bearer token;
  leave it empty for localhost-only use.

Default role map (all overridable — see "Tuning the roles"). The set is
open-source-forward: coding, thinking, and cheap lanes default to open-weight
models, with proprietary models reserved for the everyday and top-tier lanes.

| Role             | Default upstream model        | Open weights? | Use for                                   |
| ---------------- | ----------------------------- | :-----------: | ----------------------------------------- |
| `fast`           | `anthropic/claude-sonnet-4`   |       —       | everyday coding (the default role)        |
| `coding`         | `qwen/qwen3-coder`            |       ✅       | code generation / edits                   |
| `thinking`       | `deepseek/deepseek-r1`        |       ✅       | step-by-step reasoning / planning         |
| `ultra-thinking` | `anthropic/claude-opus-4`     |       —       | the hardest architecture / debugging work |
| `research`       | `google/gemini-2.5-pro`       |       —       | long-context research / reading codebases |
| `cheap`          | `deepseek/deepseek-chat`      |       ✅       | high-volume, low-stakes calls             |

> These IDs are reasonable starting points, **not** a recommendation to lock in,
> and model IDs drift (dated `-0324` / `-2507` suffixes, renames). Confirm exact
> IDs/prices at <https://openrouter.ai/models>. `roles.yaml` also lists swap-in
> alternates (e.g. `qwen/qwen-2.5-coder-32b-instruct`, `qwen/qwen3-235b-a22b`,
> `meta-llama/llama-3.3-70b-instruct`, `google/gemini-2.0-flash-001`).

## Setup guide

### Step 0 — Prerequisites

- Python 3.11+ on the host that will run the router (your "Cool" file server).
- An **OpenRouter** account + API key: <https://openrouter.ai/keys>.
- **OpenCode** installed (Step 3).

### Step 1 — Run the model router

```bash
cd model-router
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: set OPENROUTER_API_KEY=sk-or-...  (the only required value)

set -a; . ./.env; set +a
uvicorn app.main:app --host 0.0.0.0 --port 8787
```

Or with Docker:

```bash
docker build -t paperclip-model-router model-router
docker run -d --name model-router -p 8787:8787 \
  -e OPENROUTER_API_KEY=sk-or-... \
  paperclip-model-router
```

Verify:

```bash
curl -s localhost:8787/healthz | jq
curl -s localhost:8787/v1/models | jq '.data[].id'      # -> "cheap" "fast" "thinking"
curl -s localhost:8787/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"fast","messages":[{"role":"user","content":"reply with OK"}]}' | jq
```

### Step 2 — Tune the roles (optional)

Edit [`model-router/roles.yaml`](../../model-router/roles.yaml):

```yaml
roles:
  fast:
    model: anthropic/claude-sonnet-4
    description: Everyday coding (default).
  coding:
    model: qwen/qwen3-coder
    description: Open-weight Qwen3 Coder for code generation / edits.
  thinking:
    model: deepseek/deepseek-r1
    description: Open-weight DeepSeek-R1 reasoning / planning.
  ultra-thinking:
    model: anthropic/claude-opus-4
    description: Top-tier reasoning for the hardest work.
  research:
    model: google/gemini-2.5-pro
    description: Long-context research / synthesis.
  cheap:
    model: deepseek/deepseek-chat
    description: High-volume, low-stakes calls.
```

Or override one role without editing the file (handy in Docker/systemd). Note
shell env names can't contain hyphens, so `ultra-thinking` uses the underscore
form, which the router aliases back to the hyphenated role:

```bash
MODEL_ROLE_CODING=qwen/qwen3-coder
MODEL_ROLE_RESEARCH=google/gemini-2.5-pro
MODEL_ROLE_ULTRA_THINKING=anthropic/claude-opus-4   # -> ultra-thinking
```

Add as many roles as you like (`review`, `bulk`, `vision`, …) — they appear in
`/v1/models` automatically.

### Step 3 — Install OpenCode

```bash
# macOS / Linux
curl -fsSL https://opencode.ai/install | bash
# or: npm i -g opencode-ai   /   brew install sst/tap/opencode
opencode --version
```

### Step 4 — Point OpenCode at the router

OpenCode reads `opencode.json` from the project root or
`~/.config/opencode/opencode.json` globally. Add a custom OpenAI-compatible
provider whose `baseURL` is the router and whose model IDs are the role names:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "paperclip-router": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Paperclip Router",
      "options": {
        "baseURL": "http://localhost:8787/v1",
        "apiKey": "{env:ROUTER_API_KEY}"
      },
      "models": {
        "fast":           { "name": "Fast (Sonnet)" },
        "coding":         { "name": "Coding (Qwen3 Coder)" },
        "thinking":       { "name": "Thinking (DeepSeek-R1)" },
        "ultra-thinking": { "name": "Ultra-thinking (Opus)" },
        "research":       { "name": "Research (Gemini 2.5 Pro)" },
        "cheap":          { "name": "Cheap (DeepSeek V3)" }
      }
    }
  },
  "model": "paperclip-router/fast"
}
```

- `apiKey` is only consulted if you set `ROUTER_API_KEYS` on the router. For
  localhost with no router auth, any non-empty placeholder works.
- The `"model"` line sets OpenCode's default; switch interactively with the
  model picker and choose `paperclip-router/coding`, `/thinking`,
  `/ultra-thinking`, `/research`, or `/cheap` as needed.

> The provider/`npm`/`options` schema above follows OpenCode's documented
> custom-provider format. OpenCode's config evolves — confirm the current schema
> at <https://opencode.ai/docs/providers> (the egress policy in this build
> blocked live verification of that page).

### Step 5 — Use OpenCode as the PC builder

```bash
cd /path/to/paperclip
opencode            # opens the agent in this repo
```

Drive a task on the cheap model, escalate to thinking for design work, e.g.
"switch to paperclip-router/thinking and plan the refactor."

## Verification checklist

- [ ] `curl /healthz` shows `"upstream_configured": true` and your roles.
- [ ] A `model:"fast"` chat call returns a completion (router → OpenRouter OK).
- [ ] OpenCode lists `paperclip-router/*` models and completes a prompt.
- [ ] OpenRouter dashboard shows the requests under your key.
- [ ] `python -m pytest -q` passes in `model-router/` (11 tests).

## Security & ops notes

- **Keys never reach OpenCode.** The router holds `OPENROUTER_API_KEY`; clients
  only ever see role names and (optionally) a router-scoped key.
- **Turn on router auth for non-localhost.** Set `ROUTER_API_KEYS` and put the
  router behind TLS (reverse proxy) if it leaves the box.
- **Cost control.** Set per-key budgets/limits in the OpenRouter dashboard;
  use the `cheap` role for bulk work. This pairs naturally with Paperclip's
  own per-agent budget enforcement.
- **Run as a service.** On the file server, wrap `uvicorn` in systemd (or run
  the Docker container with `--restart unless-stopped`) so it survives reboots.

## Running OpenCode as a managed Paperclip employee

Paperclip already ships a first-class `opencode_local` adapter
(`packages/adapters/opencode-local/`, registered in the server/UI/CLI
registries), so OpenCode can run as a managed employee (heartbeats, tasks, cost
tracking, the org chart) without writing a new adapter.

The adapter runs `opencode run --format json` and takes a required `model` in
OpenCode `provider/model` format. Two ways to feed it our roles:

1. **Through this router (recommended for the role abstraction).** Add the
   `paperclip-router` custom provider to OpenCode's config (Step 4) and set the
   agent's `adapterConfig.model` to `paperclip-router/coding` (or any role).
   Retuning a role then changes behavior for every employee at once.

2. **Through OpenCode's built-in `openrouter` provider (no router hop).** Set
   `adapterConfig.model` directly to e.g. `openrouter/qwen/qwen3-coder` and
   provide `OPENROUTER_API_KEY` in the agent's env. Simpler, but you lose the
   central role indirection.

Example `adapterConfig` for an `opencode_local` agent using the router:

```json
{
  "name": "PC Builder (OpenCode)",
  "adapterType": "opencode_local",
  "adapterConfig": {
    "model": "paperclip-router/coding",
    "dangerouslySkipPermissions": true,
    "env": { "ROUTER_API_KEY": "<router key if ROUTER_API_KEYS is set>" }
  }
}
```

> The adapter's built-in `models` list and `cheap` model profile currently
> default to OpenAI/Codex IDs. The role variety in this plan lives in the
> router's `roles.yaml`; surfacing the same roles as adapter `modelProfiles`
> (so the Paperclip budget UI shows `coding` / `thinking` / `research` lanes) is
> a small, separate follow-up in `packages/adapters/opencode-local/src/index.ts`.
```
