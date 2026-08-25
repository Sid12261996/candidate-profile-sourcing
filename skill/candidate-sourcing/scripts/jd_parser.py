"""JD parser (spec: jd-intake - "Parse JD into a requirement profile").

Deterministic extraction of structured fields from a job description document.
Fields that cannot be determined are recorded as None (unspecified) - values
are NEVER invented. Defaults from workflow.yaml are applied only by
`apply_defaults()`, keeping raw and effective views separate.

The LLM agent layer (SKILL.md) uses this as its first pass and may enrich the
profile further; the schema below is the contract both sides share.
"""
from __future__ import annotations

import re

from config_loader import load_config

UNSPECIFIED = None

SENIORITY_PATTERNS = [
    ("lead", r"\blead\b|\bleading a team\b|\bteam lead\b"),
    ("principal", r"\bprincipal\b"),
    ("staff", r"\bstaff\b"),
    ("senior", r"\bsenior\b|\bsr\.?\b"),
    ("junior", r"\bjunior\b|\bjr\.?\b|\bassociate\b"),
]

CITY_PATTERNS = [
    "mumbai", "bengaluru", "bangalore", "delhi", "noida", "gurgaon", "gurugram",
    "hyderabad", "pune", "chennai", "kolkata", "ahmedabad", "jaipur", "indore",
    "chandigarh", "kochi", "coimbatore", "remote",
]

_EXPERIENCE_RE = [
    re.compile(r"(\d+)\s*(?:\+|plus)\s*years?", re.I),
    re.compile(r"(?:minimum|min\.?)\s*(\d+)\s*years?", re.I),
    re.compile(r"(\d+)\s*[-–]\s*(\d+)\s*years?", re.I),
    re.compile(r"over\s+(\d+)\s*years?", re.I),
]

_SECTION_ALIASES = {
    "must": ["must have", "must-have", "requirements", "required", "responsibilities"],
    "preferred": ["preferred", "nice to have", "nice-to-have", "good to have", "bonus"],
}


def _title_from_markdown(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def detect_role_family(text: str, cfg: dict | None = None) -> str | None:
    cfg = cfg or load_config()
    low = text.lower()
    best, best_hits = None, 0
    for family, spec in cfg.get("role_families", {}).items():
        hits = sum(1 for p in spec["title_patterns"] if p in low)
        if hits > best_hits:
            best, best_hits = family, hits
    return best


def detect_seniority(text: str) -> str | None:
    low = text.lower()
    for label, pattern in SENIORITY_PATTERNS:
        if re.search(pattern, low):
            return label
    return UNSPECIFIED


def detect_experience_years(text: str) -> tuple[int | None, int | None]:
    """Returns (min_years, max_years); max is None unless a range is stated."""
    for rx in _EXPERIENCE_RE[:2] + [_EXPERIENCE_RE[3]]:
        m = rx.search(text)
        if m:
            return int(m.group(1)), None
    m = _EXPERIENCE_RE[2].search(text)  # range pattern
    if m:
        return int(m.group(1)), int(m.group(2))
    return UNSPECIFIED, UNSPECIFIED


def detect_locations(text: str) -> list[str]:
    low = text.lower()
    found = [c for c in CITY_PATTERNS if re.search(rf"\b{re.escape(c)}\b", low)]
    # normalise bangalore/bengaluru duplicates
    if {"bengaluru", "bangalore"} <= set(found):
        found.remove("bangalore")
    if {"gurgaon", "gurugram"} <= set(found):
        found.remove("gurgaon")
    return found


def _extract_section(text: str, aliases: list[str]) -> list[str]:
    lines = text.splitlines()
    items, collecting = [], False
    for line in lines:
        stripped = line.strip().lstrip("#").strip().lower().rstrip(":")
        if any(stripped == a or stripped.startswith(a) for a in aliases):
            collecting = True
            continue
        if collecting:
            if re.match(r"^#{1,6}\s", line):      # next heading ends the section
                break
            if line.strip().startswith(("-", "*", "•")):
                items.append(line.strip().lstrip("-*• ").strip())
            elif items and not line.strip():
                break                              # blank line after items ends it
    return items


def detect_weights(text: str) -> dict[str, float] | None:
    """Optional 'weights' JSON/YAML-ish block, e.g. weight: portfolio=0.5."""
    pairs = dict(re.findall(r"([A-Za-z_ ]+?)\s*[=:]\s*(0?\.\d+|1(?:\.0+)?)\b", text))
    if not pairs:
        return UNSPECIFIED
    return {k.strip().lower(): float(v) for k, v in pairs.items()}


def parse_jd(text: str, cfg: dict | None = None) -> dict:
    """Raw requirement profile. Unspecified fields are None / empty."""
    return {
        "title": _title_from_markdown(text),
        "role_family": detect_role_family(text, cfg),
        "seniority": detect_seniority(text),
        "must_have": _extract_section(text, _SECTION_ALIASES["must"]),
        "preferred": _extract_section(text, _SECTION_ALIASES["preferred"]),
        "experience_band_years": {
            "min": detect_experience_years(text)[0],
            "max": detect_experience_years(text)[1],
        },
        "locations": detect_locations(text),
        "scoring_weights": detect_weights(text),
    }


def apply_defaults(profile: dict, cfg: dict | None = None) -> dict:
    """Effective profile: documented config defaults fill unspecified fields."""
    cfg = cfg or load_config()
    defaults = cfg.get("defaults", {})
    eff = json_safe = dict(profile)

    exp = dict(profile["experience_band_years"])
    d_exp = defaults.get("experience_band_years", {})
    if exp["min"] is None:
        exp["min"] = d_exp.get("min")
    if exp["max"] is None:
        exp["max"] = d_exp.get("max")
    eff["experience_band_years"] = exp

    if not profile["locations"]:
        eff["locations"] = list(defaults.get("locations", []))
    return eff


def parse_jd_effective(text: str, cfg: dict | None = None) -> dict:
    return apply_defaults(parse_jd(text, cfg), cfg)
