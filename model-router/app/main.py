"""Paperclip Model Router.

An OpenAI-compatible HTTP service that sits in front of OpenRouter and exposes
logical model *roles* (``thinking``, ``fast``, ``cheap``, ...) as model names.
Point any OpenAI-compatible client (OpenCode, the OpenAI SDK, curl) at this
service and request a role by name; the router rewrites it to the configured
upstream OpenRouter model and forwards the call, streaming or not.

Why: coding agents like OpenCode pick a model by ID. By addressing a *role*
instead of a hard-coded model, you can retune which concrete model backs
"fast" vs "thinking" vs "cheap" centrally — no agent reconfiguration needed.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .config import Settings, load_settings
from .upstream import build_upstream_headers, make_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.settings = settings
    app.state.client = make_client(settings)
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(
    title="Paperclip Model Router",
    version=__version__,
    summary="Role-based OpenAI-compatible proxy in front of OpenRouter.",
    lifespan=lifespan,
)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.client


def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """Validate the client's bearer token when ROUTER_API_KEYS is set."""
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token not in settings.router_api_keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/healthz")
async def healthz(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "upstream_configured": bool(settings.openrouter_api_key),
        "roles": sorted(settings.roles.keys()),
        "default_role": settings.default_role,
    }


@app.get("/v1/models", dependencies=[Depends(require_auth)])
async def list_models(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """List roles as OpenAI-style model objects so clients can discover them."""
    now = int(time.time())
    data = [
        {
            "id": name,
            "object": "model",
            "created": now,
            "owned_by": "paperclip-model-router",
            "paperclip_upstream_model": upstream,
            "paperclip_description": settings.role_descriptions.get(name, ""),
        }
        for name, upstream in sorted(settings.roles.items())
    ]
    return {"object": "list", "data": data}


async def _proxy(
    path: str,
    request: Request,
    settings: Settings,
    client: httpx.AsyncClient,
) -> Any:
    """Forward an OpenAI-style request body to OpenRouter, resolving the role.

    Honors ``stream: true`` by relaying the upstream SSE byte stream verbatim.
    """
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=502,
            detail="OPENROUTER_API_KEY is not configured on the router",
        )

    try:
        body: dict[str, Any] = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Request body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    requested = body.get("model")
    body["model"] = settings.resolve(requested if isinstance(requested, str) else None)

    headers = build_upstream_headers(settings)
    stream = bool(body.get("stream", False))

    if stream:
        # StreamingResponse owns the lifecycle of the upstream stream context.
        async def event_stream():
            async with client.stream(
                "POST", path, json=body, headers=headers
            ) as upstream:
                if upstream.status_code >= 400:
                    detail = await upstream.aread()
                    yield _sse_error(upstream.status_code, detail)
                    return
                async for chunk in upstream.aiter_raw():
                    yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    upstream = await client.post(path, json=body, headers=headers)
    media_type = upstream.headers.get("content-type", "application/json")
    return JSONResponse(
        status_code=upstream.status_code,
        content=_safe_json(upstream),
        media_type="application/json" if "json" in media_type else media_type,
    )


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        return {"error": {"message": resp.text, "type": "upstream_error"}}


def _sse_error(status: int, detail: bytes) -> bytes:
    try:
        parsed = json.loads(detail)
    except (json.JSONDecodeError, ValueError):
        parsed = {"error": {"message": detail.decode("utf-8", "replace")}}
    payload = {"status": status, **(parsed if isinstance(parsed, dict) else {})}
    return f"data: {json.dumps(payload)}\n\n".encode()


@app.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
async def chat_completions(
    request: Request,
    settings: Settings = Depends(get_settings),
    client: httpx.AsyncClient = Depends(get_client),
) -> Any:
    return await _proxy("/chat/completions", request, settings, client)


@app.post("/v1/completions", dependencies=[Depends(require_auth)])
async def completions(
    request: Request,
    settings: Settings = Depends(get_settings),
    client: httpx.AsyncClient = Depends(get_client),
) -> Any:
    return await _proxy("/completions", request, settings, client)
