"""LLM inference callable backed by Ollama API.

Uses local Ollama instance for rubric scoring. Model comes from
$HERMES_CRON_MODEL, endpoint from $HERMES_OLLAMA_BASE_URL.
"""
from __future__ import annotations

import json
import os
import urllib.request


class LLMError(RuntimeError):
    pass


def make_llm_fn(model: str | None = None, timeout: int = 120):
    model = model or os.environ.get("HERMES_CRON_MODEL", "deepseek-r1:8b")
    base_url = os.environ.get("HERMES_OLLAMA_BASE_URL", "http://localhost:11434")

    def llm_fn(prompt: str) -> str:
        url = f"{base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "temperature": 0,
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read())
                content = result.get("response", "").strip()
                if not content:
                    raise LLMError("empty completion from model")
                return content
        except urllib.error.HTTPError as e:
            raise LLMError(f"Ollama {e.code}: {e.read().decode()[:200]}")
        except urllib.error.URLError as e:
            raise LLMError(f"Ollama unreachable at {base_url}: {e}")
        except json.JSONDecodeError as e:
            raise LLMError(f"Ollama returned invalid JSON: {e}")

    return llm_fn
