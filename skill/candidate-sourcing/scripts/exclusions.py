"""Zero-score exclusion registry (design D5, spec candidate-shortlisting).

Records the profile URLs of every candidate that scored 0 so later runs skip
them before rubric scoring - they burn no tokens again. Stored OUTSIDE the
human-reviewed Excel ledger on purpose: automation never writes rows or
statuses into reviewer data. Entries: {url, jd, date}; purgeable by the same
retention job as rejected-ledger data.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config_loader import state_dir


def registry_path() -> Path:
    return state_dir() / "exclusions.json"


def load(path: Path | None = None) -> list[dict]:
    path = path or registry_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def urls(path: Path | None = None) -> set[str]:
    """All registered exclusion URLs (union target for pre-scoring skips)."""
    return {str(e.get("url") or "").strip()
            for e in load(path) if str(e.get("url") or "").strip()}


def append(entries: list[dict], path: Path | None = None) -> int:
    """Append {url, jd, date} entries; url+jd pairs are deduped. Returns added."""
    path = path or registry_path()
    existing = load(path)
    seen = {(str(e.get("url")), str(e.get("jd"))) for e in existing}
    added = 0
    for entry in entries:
        if not str(entry.get("url") or "").strip():
            continue
        key = (str(entry.get("url")), str(entry.get("jd")))
        if key in seen:
            continue
        seen.add(key)
        existing.append({
            "url": entry["url"],
            "jd": entry.get("jd"),
            "date": entry.get("date") or date.today().isoformat(),
        })
        added += 1
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return added


def split_records(records: list[dict], excluded_urls: set[str]) -> tuple[list[dict], list[dict]]:
    """Partition records into (pass_through, excluded) before scoring."""
    passed, dropped = [], []
    for rec in records:
        rec_urls = set(rec.get("source_urls") or [])
        if rec.get("profile_url"):
            rec_urls.add(rec["profile_url"])
        if rec_urls & excluded_urls:
            dropped.append(rec)
        else:
            passed.append(rec)
    return passed, dropped
