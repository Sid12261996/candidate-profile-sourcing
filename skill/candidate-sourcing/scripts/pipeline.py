"""Deterministic end-to-end pipeline orchestrator.

The cron agent's ONLY job: run this script, then relay the JSON summary it
prints as the run notification. Every decision lives in tested code here -
no improvised inline scripts (the lesson of integration testing).

Usage:
    python3 pipeline.py run
Output:
    {"status": "silent"}                                   -> nothing to do
    {"status": "ok", "jds": [...], "quarantined": [...],   -> relay as-is
     "deferred": [...]}
"""
from __future__ import annotations

import json
import os
import sys
import traceback

from config_loader import load_config, repo_root

SCRIPTS_OK = True


def _ledger_path(cfg) -> "Path":
    from pathlib import Path
    raw = os.environ.get("CPS_LEDGER_PATH", "data/candidates.xlsx")
    path = repo_root() / raw if not os.path.isabs(raw) else Path(raw)
    return path


def run() -> dict:
    import drive_sync
    import ingest
    import jd_parser
    import xray
    import portfolio
    import dedup
    import score_filters
    import scoring
    import topn
    import ledger

    cfg = load_config()
    get = drive_sync.get_backend
    summary = {"status": "ok", "jds": [], "quarantined": [], "deferred": []}

    # ---- Stage 0: intake sweep -------------------------------------------
    pending = drive_sync.list_pending(get=get)
    inbox = drive_sync.list_inbox(get=get)
    if not pending and not inbox:
        return {"status": "silent"}

    # ---- Stage 1: Track B ingest ------------------------------------------
    def _read_bytes(name):
        return get().read_file("exports_inbox", name).encode("utf-8")

    ingest_summary = ingest.ingest_inbox(
        list_names_fn=lambda: drive_sync.list_inbox(get=get),
        read_fn=_read_bytes,
        mark_processed_fn=lambda n: get().move("exports_inbox", n, "jds_processed"),
        quarantine_fn=lambda n: drive_sync.quarantine(
            n, src_key="exports_inbox", get=get),
    )
    exported_records = [r for item in ingest_summary["ingested"] for r in item["records"]]
    for q in ingest_summary["quarantined"]:
        summary["quarantined"].append(f"{q['file']}: {q['reason'][:80]}")

    llm_fn = None  # lazy: only needed when candidates survive filtering

    # ---- Stage 2: per-JD ---------------------------------------------------
    for name in pending:
        jd_result = {"jd": name, "discovered": 0, "filtered": 0,
                     "scored": 0, "added": 0}
        try:
            text = get().read_file("jds_pending", name)
            profile = jd_parser.parse_jd_effective(text)

            records, errors = xray.run_track_a(profile)
            p_recs, p_errors = portfolio.run_portfolio_discovery(profile)
            records += p_recs
            records += exported_records
            errors += p_errors
            jd_result["discovered"] = len(records)
            if errors:
                jd_result["notes"] = errors[:2]

            ledger_path = _ledger_path(cfg)
            rows = ledger.load_rows(ledger_path)
            excluded = ledger.excluded_urls(ledger_path)
            records = dedup.apply_dedup(records, rows)
            before = len(records)
            records = [r for r in records if r.get("dedup_status") != "duplicate"]
            survivors, eliminated = score_filters.apply_hard_filters(records, profile)
            jd_result["filtered"] = before - len(survivors)

            if survivors:
                if llm_fn is None:
                    from openrouter_llm import make_llm_fn
                    llm_fn = make_llm_fn()
                scored = []
                for rec in survivors:
                    try:
                        s = scoring.score_candidate(profile, rec, llm_fn)
                        scored.append({**rec, **s})
                    except Exception as exc:          # per-candidate isolation
                        jd_result.setdefault("score_errors", []).append(str(exc)[:80])
                scoring.save_scores(profile.get("title") or name, scored)
                jd_result["scored"] = len(scored)

                picked = topn.select_top_n(scored, excluded_urls=excluded,
                                           n=int(cfg["scoring"]["top_n_per_jd_per_run"]))
                try:
                    added = ledger.append_records(ledger_path, picked,
                                                  profile.get("title") or name)
                    jd_result["added"] = added
                    drive_sync.reset_failures(name)
                    drive_sync.mark_processed(name, get=get)
                except ledger.LedgerLockedError as exc:
                    summary["deferred"].append(f"{name}: {exc}")
                    continue                          # leave file pending
            else:
                # nothing qualified; still a successful pass -> archive JD
                drive_sync.reset_failures(name)
                drive_sync.mark_processed(name, get=get)
            jd_result.pop("discovered", None)
        except Exception as exc:                       # per-JD isolation
            traceback.print_exc(file=sys.stderr)
            drive_sync.record_failure(name)
            if drive_sync.should_quarantine(name):
                drive_sync.quarantine(name, get=get)
                drive_sync.reset_failures(name)
                summary["quarantined"].append(f"{name}: quarantined after repeated failures ({exc})")
            else:
                jd_result["error"] = str(exc)[:120]
                summary["jds"].append(jd_result)
            continue
        summary["jds"].append(jd_result)

    return summary


def main() -> int:
    print(json.dumps(run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
