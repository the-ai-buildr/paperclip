"""Thin HTTP client for talking to the OpenRouter upstream."""

from __future__ import annotations

import httpx

from .config import Settings


def build_upstream_headers(settings: Settings) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    # OpenRouter uses these for attribution / app ranking; both optional.
    if settings.http_referer:
        headers["HTTP-Referer"] = settings.http_referer
    if settings.x_title:
        headers["X-Title"] = settings.x_title
    return headers


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.openrouter_base_url,
        timeout=httpx.Timeout(settings.request_timeout_seconds, connect=15.0),
    )
