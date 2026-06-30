# Plan & Setup Guide: OpenCode + OpenRouter via a Role-Based Model Router

**Date:** 2026-06-30
**Status:** Implemented (router service) + setup guide
**Owner:** tyhunt82
**Branch:** `claude/paperclip-fastapi-router-ypdv46`

## Goal

Use **OpenCode** as a coding agent for building Paperclip ("PC"), driven by
**OpenRouter** models, addressed by **role** rather than by a hard-coded model
ID. A small **FastAPI router** sits between OpenCode and OpenRouter and maps
logical roles — `thinking`, `fast`, `cheap` — to concrete OpenRouter models.

You ask for a *model type*; the router decides *which model* serves it. Retune
the mapping in one place and every client follows, with no agent reconfig.

## Why this shape

- **OpenCode** is an open-source terminal coding agent that talks to any
  OpenAI-compatible endpoint via custom providers. That makes it a clean fit as
  a "code agent" you point at your own gateway.
- **OpenRouter** gives one API key and one OpenAI-compatible surface across many
  model vendors (Anthropic, OpenAI, DeepSeek, Google, …).
- A **role router** decouples *intent* ("I want the thinking model") from
  *selection* ("…which today is `anthropic/claude-opus-4`"). You change the
  backing model centrally; agents, scripts, and teammates keep using `thinking`.

```
┌──────────┐   model:"thinking"   ┌──────────────────────┐  model:"anthropic/   ┌────────────┐
│ OpenCode │ ───────────────────▶ │ Paperclip Model      │  claude-opus-4"      │ OpenRouter │ ─▶ model
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
  roles.yaml       # default role map (thinking / fast / cheap)
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

Default role map (all overridable — see "Tuning the roles"):

| Role       | Default upstream model        | Use for                                  |
| ---------- | ----------------------------- | ---------------------------------------- |
| `thinking` | `anthropic/claude-opus-4`     | hard reasoning, architecture, planning   |
| `fast`     | `anthropic/claude-sonnet-4`   | everyday coding (the default)            |
| `cheap`    | `deepseek/deepseek-chat`      | high-volume, low-stakes calls            |

> These IDs are reasonable starting points, not a recommendation to lock in.
> Pick exact models/prices from <https://openrouter.ai/models>.

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
  thinking:
    model: anthropic/claude-opus-4
    description: Deep reasoning / planning model.
  fast:
    model: anthropic/claude-sonnet-4
    description: Everyday coding.
  cheap:
    model: deepseek/deepseek-chat
    description: High-volume, low-stakes calls.
```

Or override one role without editing the file (handy in Docker/systemd):

```bash
MODEL_ROLE_THINKING=anthropic/claude-opus-4
MODEL_ROLE_CHEAP=google/gemini-2.0-flash-001
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
        "thinking": { "name": "Thinking (Opus via OpenRouter)" },
        "fast":     { "name": "Fast (Sonnet via OpenRouter)" },
        "cheap":    { "name": "Cheap (DeepSeek via OpenRouter)" }
      }
    }
  },
  "model": "paperclip-router/fast"
}
```

- `apiKey` is only consulted if you set `ROUTER_API_KEYS` on the router. For
  localhost with no router auth, any non-empty placeholder works.
- The `"model"` line sets OpenCode's default; switch interactively with the
  model picker and choose `paperclip-router/thinking` or `/cheap` as needed.

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
- [ ] `python -m pytest -q` passes in `model-router/` (10 tests).

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

## Optional follow-up: a first-class Paperclip OpenCode adapter

The router lets OpenCode run as a standalone coding tool today. To make OpenCode
a *managed Paperclip employee* (heartbeats, tasks, cost tracking, the org
chart), add an adapter package following the existing `codex-local` pattern:

- `packages/adapters/opencode-local/` implementing the `ServerAdapterModule`,
  `UIAdapterModule`, and `CLIAdapterModule` interfaces (see the
  `create-agent-adapter` skill in `.agents/skills/`).
- `execute.ts` spawns the `opencode` CLI in non-interactive mode, injects the
  Paperclip runtime env (`PAPERCLIP_API_URL`, `PAPERCLIP_API_KEY`,
  `PAPERCLIP_RUN_ID`), and parses stdout into `TranscriptEntry` objects.
- Set the adapter's model config to a `paperclip-router/<role>` provider so
  employees inherit the same role abstraction.

That is a larger effort and intentionally out of scope for this branch, which
delivers the router + integration path. Flagging it as the natural next step.
```
