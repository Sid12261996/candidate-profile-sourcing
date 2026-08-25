"""Single search() boundary for Track A discovery (design D4).

Every sourcing query - x-ray or portfolio - flows through this module so
backends can be swapped (SearXNG -> paid providers) without touching pipeline
code. No backend here ever authenticates to LinkedIn/Naukri (spec: candidate-
discovery "No authenticated platform access").

Primary:   SearXNG JSON API (compose service).
Fallback:  duckduckgo_search library, only when SearXNG is unreachable.
"""
from __future__ import annotations

import os

import requests

from config_loader import load_config


class SearchBackendError(RuntimeError):
    """Raised when no search backend can serve a query."""


def _base_url() -> str:
    key = load_config()["search_backend"].get("base_url_env", "SEARXNG_BASE_URL")
    return os.environ.get(key, "http://localhost:8080").rstrip("/")


def _searxng(query: str, max_results: int) -> list[dict]:
    resp = requests.get(
        f"{_base_url()}/search",
        params={"q": query, "format": "json"},
        headers={"User-Agent": "candidate-sourcing/0.1"},
        timeout=30,
    )
    resp.raise_for_status()
    results = []
    for item in resp.json().get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        })
    return results


def _duckduckgo(query: str, max_results: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS  # lazy: optional dependency
    except ImportError as exc:  # pragma: no cover
        raise SearchBackendError("fallback backend 'duckduckgo_search' not installed") from exc
    with DDGS() as ddgs:
        hits = ddgs.text(query, max_results=max_results)
        return [
            {"title": h.get("title", ""), "url": h.get("href", ""),
             "snippet": h.get("body", "")}
            for h in hits
        ]


def search(query: str, max_results: int = 20) -> list[dict]:
    """Run one public-web query. Raises SearchBackendError when both backends fail."""
    try:
        return _searxng(query, max_results)
    except (requests.RequestException, ValueError):
        pass  # unreachable / non-JSON -> try fallback
    try:
        return _duckduckgo(query, max_results)
    except Exception as exc:
        raise SearchBackendError(f"all search backends failed for: {query!r}") from exc
