"""LLM inference via Anthropic Claude API.

Used for query-expansion planning in the candidate-discovery stage.
The Claude API key comes from $CLAUDE_API_KEY (set at Hermes runtime).
"""
from __future__ import annotations

import os


class LLMError(RuntimeError):
    pass


def make_llm_fn(model: str = "claude-opus-5", timeout: int = 120):
    """Create an LLM callable backed by the Anthropic Claude API.

    Args:
        model: Claude model ID (default: claude-opus-5)
        timeout: Request timeout in seconds

    Returns:
        A callable(prompt: str) -> str that calls Claude

    Raises:
        LLMError: If $CLAUDE_API_KEY is not set or if API call fails
    """
    key = os.environ.get("CLAUDE_API_KEY")
    if not key:
        raise LLMError("$CLAUDE_API_KEY not set - cannot perform query expansion")

    try:
        from anthropic import Anthropic
    except ImportError:
        raise LLMError("anthropic SDK not available; install with: pip install anthropic")

    client = Anthropic(api_key=key)

    def llm_fn(prompt: str) -> str:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )
            content = response.content[0].text if response.content else ""
            if not content:
                raise LLMError("empty completion from Claude")
            return content
        except Exception as e:
            raise LLMError(f"Claude API error: {str(e)[:200]}")

    return llm_fn
