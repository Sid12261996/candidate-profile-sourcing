"""Stage 2 of evaluation: LLM rubric scoring (task 7.2, design D5).

The LLM itself is injected as `llm_fn(prompt) -> str`, keeping this module
deterministic and testable offline; the agent session supplies the real call
(pinned model per run-orchestration spec "Cost-bounded operation").
Scores + justifications are persisted per run for audit.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config_loader import state_dir

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "rubric_scoring.md"


def load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict:
    """Tolerant JSON extraction: strips fences/prose around the object."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", text, re.S)
        text = match.group(0) if match else text
    return json.loads(text)


def score_candidate(profile: dict, record: dict, llm_fn) -> dict:
    locations = ", ".join(profile.get("locations") or []) or "(stated in JD profile)"
    prompt = (load_prompt()
              .replace("{{jd_profile}}", json.dumps(profile, default=str))
              .replace("{{candidate}}", json.dumps(record, default=str))
              .replace("{{onsite_locations}}", locations))
    parsed = _extract_json(llm_fn(prompt))
    score = max(0, min(100, int(parsed["score"])))
    return {
        "score": score,
        "justification": str(parsed.get("justification", "")).strip(),
        "profile_url": record.get("profile_url"),
    }


def save_scores(jd_title: str, scored: list[dict]) -> Path:
    out_dir = state_dir() / "scores"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", jd_title)[:60] or "untitled"
    path = out_dir / f"{stamp}_{safe}.json"
    path.write_text(json.dumps(scored, indent=2), encoding="utf-8")
    return path
