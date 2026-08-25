"""LLM inference callable backed by the OpenRouter API.

Lets deterministic pipeline code perform rubric scoring without an agent
turn: the model comes from $HERMES_CRON_MODEL (pinned by run-local.sh),
the key from $OPENROUTER_API_KEY. No other provider is contacted.
"""
from __future__ import annotations

import os

import requests

_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    pass


def make_llm_fn(model: str | None = None, timeout: int = 120):
    model = model or os.environ.get("HERMES_CRON_MODEL", "openai/gpt-4o-mini")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY not set - cannot score candidates")

    def llm_fn(prompt: str) -> str:
        resp = requests.post(
            _API_URL,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"OpenRouter {resp.status_code}: {resp.text[:200]}")
        content = (resp.json().get("choices") or [{}])[0].get("message", {}).get("content")
        if not content:
            raise LLMError("empty completion from model")
        return content

    return llm_fn
