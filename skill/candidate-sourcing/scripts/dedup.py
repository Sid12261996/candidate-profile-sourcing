"""Duplicate detection across tracks and prior runs (task 7.4, design D6).

Identity strategy:
  1. exact URL match on any known profile URL
  2. fuzzy normalized name + employer similarity (difflib)
Outcomes: 'new' | 'duplicate' (confident merge/suppress) |
          'possible-duplicate' (uncertain -> surfaced to human, never hidden).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from config_loader import load_config
from ledger import TERMINAL_STATUSES

_STOPWORDS = {"ltd", "limited", "pvt", "private", "inc", "llp", "co", "company",
              "technologies", "technology", "solutions", "studios", "studio"}


def _norm_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (value or "").lower()).strip()


def _norm_company(value: str | None) -> str:
    words = [w for w in _norm_text(value).split() if w not in _STOPWORDS]
    return " ".join(words)


def _row_name(row: dict) -> str | None:
    return row.get("candidate_name") or row.get("name")


def _row_company(row: dict) -> str | None:
    return row.get("company") or row.get("current_company")


def _urls_of(row_or_rec: dict) -> set[str]:
    urls = set(row_or_rec.get("source_urls") or [])
    if row_or_rec.get("profile_url"):
        urls.add(row_or_rec["profile_url"])
    return urls


def classify(record: dict, ledger_rows: list[dict],
             cfg: dict | None = None) -> tuple[str, dict | None]:
    """Compare one incoming record against existing ledger rows."""
    cfg = cfg or load_config()
    threshold = float(cfg.get("dedup", {}).get("fuzzy_name_employer", {})
                      .get("threshold", 0.85))
    rec_urls = _urls_of(record)
    rec_name = _norm_text(record.get("name"))
    rec_co = _norm_company(record.get("company"))

    best_row, best_score = None, 0.0
    for row in ledger_rows:
        row_urls = {u.split(":")[0].startswith("naukri:") and u or u
                    for u in _urls_of(row)}
        # 1. exact URL overlap -> confident duplicate
        if rec_urls and (rec_urls & row_urls):
            return "duplicate", row

        # 2. fuzzy name+employer similarity
        name_sim = SequenceMatcher(
            None, rec_name, _norm_text(_row_name(row))).ratio()
        co_sim = SequenceMatcher(
            None, rec_co, _norm_company(_row_company(row))).ratio()
        combined = (name_sim * 0.7 + co_sim * 0.3) if (rec_name and rec_co) else name_sim
        if combined > best_score:
            best_row, best_score = row, combined

    if best_score >= threshold:
        return "possible-duplicate", best_row   # surfaced to human, not silent
    return "new", None


def apply_dedup(records: list[dict], ledger_rows: list[dict],
                cfg: dict | None = None,
                allowed_urls: set[str] | None = None,
                jd_key: str | None = None) -> list[dict]:
    """Annotate each record with 'dedup_status' and matched ledger identity.

    Spec semantics:
      duplicate           -> suppressed upstream (never occupies a top-N slot)
      possible-duplicate  -> KEPT but flagged; humans decide
      new                 -> flows through untouched

    `allowed_urls` + `jd_key` (design D3): URLs of the re-added JD's own prior
    NON-terminal rows. Only rows that (a) hold one of those URLs, (b) are not
    terminal, and (c) carry this jd_key / no source_jd at all are exempt from
    suppression - so re-processing can re-admit its own earlier picks while
    terminal statuses and other JDs' rows suppress unconditionally.
    """
    allowed = {u for u in (allowed_urls or set()) if u}
    if allowed:
        exempt_ids = []
        for i, row in enumerate(ledger_rows):
            status = str(row.get("status") or "").strip().lower()
            overlaps = bool(_urls_of(row) & allowed)
            own = (not str(row.get("source_jd") or "").strip()
                   or jd_key is None or row.get("source_jd") == jd_key)
            if overlaps and status not in TERMINAL_STATUSES and own:
                exempt_ids.append(i)
        ledger_rows = [row for i, row in enumerate(ledger_rows)
                       if i not in exempt_ids]
    out = []
    for rec in records:
        status, matched = classify(rec, ledger_rows, cfg)
        rec = {**rec, "dedup_status": status}
        if matched is not None:
            rec["matched_ledger_name"] = _row_name(matched)
        out.append(rec)
    return out
