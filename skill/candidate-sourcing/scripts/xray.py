"""Track A: x-ray search over public professional profiles (task 5.2).

Builds site-restricted queries from the requirement profile and parses SERP
results into normalized candidate records. Reads only what public search
engines expose - no logins, no authenticated calls (spec: Track A x-ray).
"""
from __future__ import annotations

import re

import search
from candidate_schema import make_record
from config_loader import load_config

_SITE = "site:linkedin.com/in"


def build_queries(profile: dict, cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    cap = int(cfg["search_backend"]["max_queries_per_jd_per_run"])

    role_terms = profile.get("title") or ""
    if not role_terms and profile.get("role_family"):
        family_specs = cfg.get("role_families", {}).get(profile["role_family"], {})
        role_terms = " OR ".join(f'"{p}"' for p in family_specs.get("title_patterns", []))
    if not role_terms:
        return []

    locations = profile.get("locations") or [None]
    queries = []
    for loc in locations:
        loc_part = f' "{loc}"' if loc else ""
        queries.append(f'{_SITE} "{role_terms}"{loc_part}')
    return queries[:cap]


_NAME_SPLIT_RE = re.compile(r"\s+[-\u2013\u2022|]\s+")


def parse_result(result: dict) -> dict | None:
    """SERP item -> candidate record. LinkedIn results look like:
    title='Name - Job Title - Company | LinkedIn', url='https://in.linkedin.com/in/slug'
    """
    url = result.get("url", "")
    if "linkedin.com/in/" not in url:
        return None
    raw_title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", result.get("title", "")).strip()
    parts = _NAME_SPLIT_RE.split(raw_title)
    name = parts[0].strip() or None
    headline = " - ".join(parts[1:]).strip() or None
    rec = make_record(
        name=name,
        title=headline,
        track="xray",
        source_urls=[url],
    )
    rec["snippet"] = result.get("snippet", "")
    return rec


def run_track_a(profile: dict, cfg: dict | None = None,
                search_fn=search.search) -> tuple[list[dict], list[str]]:
    """Discover candidates for one JD profile.

    Returns (records, errors). Per spec (graceful degradation): a backend
    failure contributes zero records and an error note - never raises out.
    """
    cfg = cfg or load_config()
    records_by_url: dict[str, dict] = {}
    errors: list[str] = []

    for query in build_queries(profile, cfg):
        try:
            for result in search_fn(query):
                rec = parse_result(result)
                if rec is None:
                    continue
                url = rec["profile_url"]
                existing = records_by_url.get(url)
                if existing is None:
                    records_by_url[url] = rec
        except search.SearchBackendError as exc:
            errors.append(str(exc))

    ordered = sorted(records_by_url.values(), key=lambda r: r["profile_url"])
    return ordered, errors
