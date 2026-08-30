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
from pathlib import Path

from config_loader import load_config, repo_root

SCRIPTS_OK = True


def _ledger_path(cfg) -> Path:
    raw = os.environ.get("CPS_LEDGER_PATH", "data/candidates.xlsx")
    path = repo_root() / raw if not os.path.isabs(raw) else Path(raw)
    return path


def run() -> dict:
    import drive_sync
    import ingest
    import jd_parser
    import query_expander
    import xray
    import portfolio
    import dedup
    import score_filters
    import scoring
    import exclusions
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

    # Reprocessing detection (design D3): a pending filename already present
    # in jds-processed marks a re-added JD -> full fresh pass; its own prior
    # non-terminal ledger rows stop suppressing (terminal ones never do).
    processed_names = set(get().list_names("jds_processed"))

    # Zero-score exclusion registry (design D5), loaded once per run and
    # unioned with ledger terminal URLs at use time.
    registry_urls = exclusions.urls()

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

    llm_fn = None  # lazy: needed for expansion and/or scoring

    def _llm():
        """Lazily-built llm_fn; creation errors surface at first call so
        expansion degrades to its template fallback instead of dying."""
        def call(prompt: str) -> str:
            nonlocal llm_fn
            if llm_fn is None:
                from ollama_llm import make_llm_fn
                llm_fn = make_llm_fn()
            return llm_fn(prompt)
        return call

    # ---- Stage 2: per-JD ---------------------------------------------------
    for name in pending:
        jd_result = {"jd": name, "discovered": 0, "filtered": 0,
                     "scored": 0, "added": 0}
        try:
            text = get().read_file("jds_pending", name)
            profile = jd_parser.parse_jd_effective(text)

            # ---- expansion stage (design D4): validated plan slice ------
            plan_batch, exp_meta = None, {"executed_queries": 0}
            try:
                plan_batch, exp_meta = query_expander.ensure_and_consume(
                    profile, text, Path(name).stem, _llm(), cfg)
                jd_result["executed_queries"] = exp_meta["executed_queries"]
                if exp_meta["plan_source"] and exp_meta["plan_source"] != "llm":
                    jd_result.setdefault("notes", []).append(
                        f"query-expansion fell back to templates"
                        f" ({exp_meta['planned_queries']} planned)")
            except Exception as exc:               # expansion must never kill a run
                jd_result.setdefault("notes", []).append(
                    f"query-expansion unavailable ({str(exc)[:60]})")
                jd_result["executed_queries"] = 0

            records, errors = xray.run_track_a(profile, cfg=cfg,
                                               queries=plan_batch)
            p_recs, p_errors = portfolio.run_portfolio_discovery(profile, cfg)
            records += p_recs
            records += exported_records
            errors += p_errors
            jd_result["discovered"] = len(records)
            if errors:
                jd_result.setdefault("notes", []).extend(errors[:2])

            ledger_path = _ledger_path(cfg)
            rows = ledger.load_rows(ledger_path)
            excluded = ledger.excluded_urls(ledger_path)
            reprocessing = name in processed_names
            if reprocessing:
                jd_result["reprocess"] = True
            allowed_urls = set()
            if reprocessing:
                allowed_urls = ledger.prior_own_urls(
                    ledger_path, name, jd_title=profile.get("title"))
            records = dedup.apply_dedup(records, rows, cfg,
                                        allowed_urls=allowed_urls, jd_key=name)
            before = len(records)
            records = [r for r in records if r.get("dedup_status") != "duplicate"]

            # pre-scoring exclusion skip: registry hits burn no rubric tokens
            records, reg_skipped = exclusions.split_records(records, registry_urls)
            if reg_skipped:
                jd_result["exclusion_skipped"] = len(reg_skipped)

            survivors, eliminated = score_filters.apply_hard_filters(
                records, profile, cfg)
            jd_result["filtered"] = before - len(survivors)

            if survivors:
                # cost cap (design D-risks): bound LLM rubric calls per JD/run
                cap = int(cfg["scoring"].get("max_scored_per_jd_per_run", 0) or 0)
                if cap and len(survivors) > cap:
                    jd_result["score_cap_deferred"] = len(survivors) - cap
                    survivors = survivors[:cap]

                scored = []
                for rec in survivors:
                    try:
                        s = scoring.score_candidate(profile, rec, _llm())
                        scored.append({**rec, **s})
                    except Exception as exc:          # per-candidate isolation
                        jd_result.setdefault("score_errors", []).append(str(exc)[:80])
                scoring.save_scores(profile.get("title") or name, scored)
                jd_result["scored"] = len(scored)

                # register zero-score candidates so later runs skip them
                if cfg["scoring"].get("exclude_zero_scores", True):
                    zero_entries = [
                        {"url": u, "jd": name}
                        for rec in scored
                        if int(rec.get("score") or 0) == 0
                        for u in ({rec.get("profile_url")}
                                  | set(rec.get("source_urls") or [])) if u
                    ]
                    if zero_entries:
                        exclusions.append(zero_entries)
                        registry_urls |= {e["url"] for e in zero_entries}

                picked = topn.select_top_n(
                    scored, excluded_urls=excluded,
                    n=int(cfg["scoring"]["top_n_per_jd_per_run"]),
                    drop_zero_scores=bool(cfg["scoring"].get("exclude_zero_scores", True)))
                try:
                    added = ledger.append_records(ledger_path, picked,
                                                  profile.get("title") or name,
                                                  source_jd=name)
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
