"""Candidate record normalization (shared schema for all tracks).

Spec: candidate-discovery "Candidate record normalization".
Track values: 'xray' | 'portfolio' | 'platform-export'.
"""
from __future__ import annotations

TRACKS = ("xray", "portfolio", "platform-export")


def make_record(*, name=None, title=None, company=None, location=None,
                experience_years=None, track="", source_urls=(),
                scored_for_jd=None) -> dict:
    if track not in TRACKS:
        raise ValueError(f"track must be one of {TRACKS}, got {track!r}")
    return {
        "name": name,
        "title": title,
        "company": company,
        "location": location,
        "experience_years": experience_years,
        # primary profile URL = first source URL when present
        "profile_url": source_urls[0] if source_urls else None,
        "source_urls": list(source_urls),
        "track": track,
        "scored_for_jd": scored_for_jd,
        # populated downstream: score, justification, possible_duplicate
    }


def merge_records(primary: dict, secondary: dict) -> dict:
    """Merge two records believed to be the same person; keep both sources."""
    merged = dict(primary)
    merged["source_urls"] = sorted(
        {u for u in primary.get("source_urls", [])} | {u for u in secondary.get("source_urls", [])}
    )
    merged["profile_url"] = merged["source_urls"][0] if merged["source_urls"] else None
    for field in ("title", "company", "location", "experience_years"):
        if not merged.get(field) and secondary.get(field):
            merged[field] = secondary[field]
    return merged
