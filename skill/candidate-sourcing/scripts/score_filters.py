"""Stage 1 of evaluation: deterministic hard filters (task 7.1, design D5).

Runs before any LLM call so obviously-wrong candidates cost zero tokens.
Missing data NEVER silently rejects - it passes through flagged
(spec: candidate-shortlisting "Hard filters precede a scoring").
"""
from __future__ import annotations

from config_loader import load_config

# Curated non-India country/city signals (design D1, layer 2). A resolved
# location containing any of these eliminates - narrow list to avoid false
# positives; every elimination is logged with its reason for review.
NON_INDIA_SIGNALS = [
    "usa", "united states", "u.s.", "canada", "uk", "united kingdom", "england",
    "london", "singapore", "uae", "dubai", "abu dhabi", "qatar", "doha",
    "saudi", "australia", "sydney", "melbourne", "new zealand", "germany",
    "berlin", "netherlands", "amsterdam", "france", "paris", "japan", "tokyo",
]

# Explicit on-site unwillingness signals in headline/snippet. Narrow by design:
# only statements about the person's own working preference eliminate.
REMOTE_ONLY_PATTERNS = [
    "remote only", "remote-only", "100% remote", "open to remote roles only",
    "not open to relocation", "no relocation", "relocation not possible",
    "remote work only", "seeking remote", "looking for remote",
]


def _location_matches(record_loc: str, accepted: list[str]) -> bool:
    loc = (record_loc or "").lower()
    return any(city in loc for city in accepted)


def apply_hard_filters(records: list[dict], profile: dict,
                       cfg: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (survivors, eliminated). Survivors may carry 'unverified' flags."""
    cfg = cfg or load_config()
    geo = cfg.get("geography", {})
    allowed_country = str(geo.get("allowed_country") or "india").lower()
    enforce_geo = bool(geo.get("enforce_hard_filter", True))
    enforce_mode = bool(cfg.get("hard_filters", {}).get("work_mode_enforcement", True))
    onsite_required = profile.get("work_mode") == "onsite"

    exp_min = (profile.get("experience_band_years") or {}).get("min")
    locations = [c.lower() for c in (profile.get("locations") or [])]

    survivors, eliminated = [], []
    for rec in records:
        unverified = []
        drop_reasons = []

        loc_text = str(rec.get("location") or "").lower()
        # headline lives in 'title', snippet in 'snippet' (candidate schema)
        blob = " ".join(str(rec.get(f) or "") for f in ("title", "snippet")).lower()

        if enforce_geo:
            if rec.get("location"):
                if any(sig in loc_text for sig in NON_INDIA_SIGNALS):
                    drop_reasons.append(
                        f"non-{allowed_country} location '{rec['location']}'")
                elif locations and not _location_matches(rec["location"], locations):
                    drop_reasons.append(f"location '{rec['location']}' outside {locations}")
            else:
                unverified.append("location")          # never silent-reject

        if enforce_mode and onsite_required:
            hit = next((p for p in REMOTE_ONLY_PATTERNS if p in blob), None)
            if hit:
                drop_reasons.append(f"on-site unwillingness signal '{hit}'")

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
