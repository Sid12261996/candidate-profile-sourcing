"""Stage 1 of evaluation: deterministic hard filters (task 7.1, design D5).

Runs before any LLM call so obviously-wrong candidates cost zero tokens.
Missing data NEVER silently rejects - it passes through flagged
(spec: candidate-shortlisting "Hard filters precede a scoring").
"""
from __future__ import annotations


def _location_matches(record_loc: str, accepted: list[str]) -> bool:
    loc = (record_loc or "").lower()
    return any(city in loc for city in accepted)


def apply_hard_filters(records: list[dict], profile: dict) -> tuple[list[dict], list[dict]]:
    """Returns (survivors, eliminated). Survivors may carry 'unverified' flags."""
    exp_min = (profile.get("experience_band_years") or {}).get("min")
    locations = [c.lower() for c in (profile.get("locations") or [])]

    survivors, eliminated = [], []
    for rec in records:
        unverified = []
        drop_reasons = []

        if locations:
            if rec.get("location"):
                if not _location_matches(rec["location"], locations):
                    drop_reasons.append(f"location '{rec['location']}' outside {locations}")
            else:
                unverified.append("location")          # never silent-reject

        if exp_min is not None:
            years = rec.get("experience_years")
            if years is not None:
                if years < exp_min:
                    drop_reasons.append(f"{years}y < required {exp_min}y")
            else:
                unverified.append("experience")        # never silent-reject

        if drop_reasons:
            eliminated.append({**rec, "eliminated_because": "; ".join(drop_reasons)})
        else:
            survivors.append({**rec, "unverified": unverified})
    return survivors, eliminated
