"""LLM-assisted query expansion (design D4, spec candidate-discovery).

Before discovery, the LLM turns the effective requirement profile + raw JD
text into a broad search plan: distinct query strings spanning title variants,
must/preferred skills, tools, seniority, and on-site city tags. The plan is
validated (JSON array, case-insensitive dedupe, India scoping enforced,
min/max combination bounds) and persisted; execution consumes it under the
per-JD budget and resumes across runs.

Failure or a too-short plan falls back to deterministic template expansion
(role patterns x cities x skills) so the funnel always starts wide.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from config_loader import load_config, state_dir

INDIA_TERMS = (
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "noida", "gurgaon",
    "gurugram", "hyderabad", "pune", "chennai", "kolkata", "ahmedabad",
    "jaipur", "indore", "chandigarh", "kochi", "coimbatore",
)

EXPANSION_PROMPT = """You are a sourcing strategist building web-search queries to find candidates in India.

## Job requirement profile
{profile}

## Raw job description
{jd_text}

Generate between {min_n} and {max_n} DISTINCT search query strings that together span these dimensions:
- title synonyms and role-family patterns for this role
- each must-have skill, preferred skill, and tool named in the JD
- seniority qualifiers matching the JD (e.g. lead, senior, associate)
- every on-site city from the profile as a location tag
- portfolio-site variants (site:behance.net / site:dribbble.com) if this is a design role

Rules:
- EVERY query must include India scoping - an Indian city name in quotes and/or the word India.
- No duplicates (case-insensitive). Plain strings only, no explanations.
Respond with ONLY a JSON array of strings.
"""


def _is_india_scoped(query: str) -> bool:
    low = query.lower()
    return any(term in low for term in INDIA_TERMS)


def _validate_queries(raw: list, cfg: dict) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        q = re.sub(r"\s+", " ", item.strip())
        if not q or not _is_india_scoped(q):
            continue
        key = q.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        max_n = int(cfg["expansion"]["max_combinations"])
        if len(out) >= max_n:
            break
    return out


def _template_plan(profile: dict, cfg: dict) -> list[str]:
    """Deterministic fallback: role patterns x cities x skills x seniority."""
    families = cfg.get("role_families", {})
    family = families.get(profile.get("role_family") or "", {})
    titles = [profile.get("title")] if profile.get("title") else []
    titles += list(family.get("title_patterns") or [])
    titles = sorted({t for t in titles if t})

    skills = []
    for section in ("must_have", "preferred"):
        for item in profile.get(section) or []:
            head = re.split(r"[,:()]", item)[0].strip()
            words = [w for w in head.split() if len(w) > 2][:3]
            if words:
                skills.append(" ".join(words))
    skills = sorted({s.lower() for s in skills})[:12]

    locations = list(profile.get("locations") or []) or ["india"]
    seniority = [None]
    if profile.get("seniority"):
        seniority.append(profile["seniority"])

    queries: list[str] = []
    for t in titles:
        for loc in locations:
            base = [f'"{t}"', f'"{loc}"'] if loc != "india" else [f'"{t}"']
            tail = " ".join(base)
            queries.append(f"{tail} india")
            for s in skills:
                queries.append(f'{tail} "{s}" india')
                for sen in seniority[1:]:
                    queries.append(f'{tail} "{sen}" "{s}" india')

    # dedupe case-insensitively
    seen: set[str] = set()
    full: list[str] = []
    for q in queries:
        key = q.casefold()
        if key not in seen:
            seen.add(key)
            full.append(q)

    # cap while keeping dimension coverage: even stride beats head-truncation
    max_n = int(cfg["expansion"]["max_combinations"])
    if len(full) > max_n:
        stride = -(-len(full) // max_n)
        full = full[::stride][:max_n]
    return full


def generate_plan(profile: dict, jd_text: str, llm_fn,
                  cfg: dict | None = None) -> tuple[list[str], str]:
    """Build a validated expansion plan.

    Returns (queries, source) where source is 'llm' | 'fallback'. Falls back
    to deterministic templates when the LLM fails or returns fewer than
    `expansion.min_combinations` valid queries (spec scenario).
    """
    cfg = cfg or load_config()
    min_n = int(cfg["expansion"]["min_combinations"])

    try:
        prompt = EXPANSION_PROMPT.format(
            profile=json.dumps(profile, default=str),
            jd_text=jd_text[:4000],
            min_n=min_n,
            max_n=int(cfg["expansion"]["max_combinations"]),
        )
        parsed = json.loads(llm_fn(prompt))
        if not isinstance(parsed, list):
            raise ValueError("plan is not a JSON array")
        queries = _validate_queries(parsed, cfg)
    except Exception:
        queries = []

    if len(queries) >= min_n:
        return queries, "llm"

    fallback = _template_plan(profile, cfg)
    # keep any valid LLM queries first, top up with templates, stay within bounds
    combined: list[str] = []
    seen: set[str] = set()
    for q in queries + fallback:
        key = q.casefold()
        if key not in seen:
            seen.add(key)
            combined.append(q)
    source = "llm+fallback" if queries else "fallback"
    return combined, source


def next_batch(plan_path, cfg: dict | None = None) -> tuple[list[str], dict]:
    """Consume the next slice of a persisted plan under the per-JD run budget.

    plan_path: Path to <state>/query-plans/<jd>.json holding
               {"queries": [...], "executed": <count consumed so far>}.
    Returns (batch, updated_state_dict); caller persists updated_state back.
    Resume semantics: a partially consumed plan continues where it stopped.
    """
    cfg = cfg or load_config()
    budget = int(cfg["search_backend"]["max_queries_per_jd_per_run"])
    state = json.loads(plan_path.read_text(encoding="utf-8"))
    start = int(state.get("executed", 0))
    batch = state["queries"][start : start + budget]
    state["executed"] = start + len(batch)
    return batch, state


def plan_path_for(jd_key: str) -> Path:
    """Per-JD persisted plan location (workflow state dir, query-plans/)."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", jd_key)[:60] or "untitled"
    return state_dir() / "query-plans" / f"{safe}.json"


def save_plan(plan_path, queries: list[str], source: str) -> dict:
    """Write a fresh validated plan; resets any previous consumption cursor."""
    state = {"queries": list(queries), "executed": 0, "source": source}
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def persist_state(plan_path, state: dict) -> None:
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def plan_complete(state: dict) -> bool:
    return int(state.get("executed", 0)) >= len(state.get("queries", []))


def ensure_and_consume(profile: dict, jd_text: str, jd_key: str, llm_fn,
                       cfg: dict | None = None) -> tuple[list[str] | None, dict]:
    """Pipeline-facing helper (design D4 consume-and-resume).

    Generates + persists a plan when absent or already fully consumed, then
    returns the next budget-sized batch with summary metadata. Returns
    (None, meta) when expansion is disabled - caller uses built-in queries.
    """
    cfg = cfg or load_config()
    path = plan_path_for(jd_key)
    meta = {"plan_source": None, "planned_queries": 0, "executed_queries": 0}

    if not cfg.get("expansion", {}).get("enabled", False):
        return None, meta

    need_fresh = True
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not plan_complete(existing):
                need_fresh = False      # resume the partially consumed plan
        except (json.JSONDecodeError, OSError):
            pass                        # corrupt plan -> regenerate

    if need_fresh:
        queries, source = generate_plan(profile, jd_text, llm_fn, cfg)
        save_plan(path, queries, source)

    batch, updated = next_batch(path, cfg)
    persist_state(path, updated)
    meta.update({
        "plan_source": updated.get("source"),
        "planned_queries": len(updated.get("queries", [])),
        "executed_queries": len(batch),
    })
    return (batch or None), meta
