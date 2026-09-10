"""Deterministic end-to-end pipeline orchestrator.

The cron agent's ONLY job: run this script, then relay the JSON summary it
prints as the run notification. Every decision lives in tested code here -
no improvised inline scripts (the lesson of integration testing).

Usage:
    python3 pipeline.py run
Output:
    {"status": "silent"}                                   -> nothing to do
    {"status": "ok", "jds": [...], "quarantined": [...],   -> relay as-is
     "deferred": [...], "ledger_delivered": true/false}
"""
from __future__ import annotations

import json
import os
import sys
import time
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

    run_start_time = time.time()
    time_budget_minutes = cfg.get("iteration", {}).get("time_budget_minutes", 20)
    max_passes = cfg.get("iteration", {}).get("max_passes", 3)

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

    expansion_llm_fn = None  # Claude API (lazy)
    scoring_llm_fn = None    # OpenRouter (lazy)

    def _expansion_llm():
        """Lazily-built Claude LLM for query expansion (fallback to Ollama if unavailable).
        Creation errors surface at first call so expansion degrades
        to its template fallback instead of dying."""
        def call(prompt: str) -> str:
            nonlocal expansion_llm_fn
            if expansion_llm_fn is None:
                try:
                    from claude_llm import make_llm_fn
                    expansion_llm_fn = make_llm_fn()
                except Exception:
                    # Claude API not available, fall back to Ollama
                    from ollama_llm import make_llm_fn as make_ollama_llm
                    expansion_llm_fn = make_ollama_llm()
            return expansion_llm_fn(prompt)
        return call

    def _scoring_llm():
        """Lazily-built LLM for rubric scoring (Claude API or Ollama based on provider)."""
        def call(prompt: str) -> str:
            nonlocal scoring_llm_fn
            if scoring_llm_fn is None:
                provider = os.environ.get("HERMES_CRON_PROVIDER", "ollama").lower()
                try:
                    if provider == "anthropic":
                        from claude_llm import make_llm_fn
                        model = os.environ.get("HERMES_CRON_MODEL", "claude-sonnet-5")
                        scoring_llm_fn = make_llm_fn(model=model)
                    else:
                        from ollama_llm import make_llm_fn
                        scoring_llm_fn = make_llm_fn()
                except Exception as e:
                    # Fallback to Ollama if primary provider fails
                    from ollama_llm import make_llm_fn
                    scoring_llm_fn = make_llm_fn()
            return scoring_llm_fn(prompt)
        return call

    # ---- Stage 2: per-JD ---------------------------------------------------
    ledger_path = _ledger_path(cfg)
    ledger_size_before = ledger_path.stat().st_size if ledger_path.exists() else 0

    for name in pending:
        jd_result = {"jd": name, "discovered": 0, "filtered": 0,
                     "scored": 0, "added": 0, "iterations": 0}
        try:
            text = get().read_file("jds_pending", name)
            profile = jd_parser.parse_jd_effective(text)

            # ---- expansion stage (design D4): validated plan slice ------
            plan_batch, exp_meta = None, {"executed_queries": 0}
            try:
                plan_batch, exp_meta = query_expander.ensure_and_consume(
                    profile, text, Path(name).stem, _expansion_llm(), cfg)
                jd_result["executed_queries"] = exp_meta["executed_queries"]
                if exp_meta["plan_source"] and exp_meta["plan_source"] != "llm":
                    jd_result.setdefault("notes", []).append(
                        f"query-expansion fell back to templates"
                        f" ({exp_meta['planned_queries']} planned)")
            except Exception as exc:               # expansion must never kill a run
                jd_result.setdefault("notes", []).append(
                    f"query-expansion unavailable ({str(exc)[:60]})")
                jd_result["executed_queries"] = 0

            # Load ledger once per JD; reload per iteration for fresh dedup
            rows = ledger.load_rows(ledger_path)
            excluded = ledger.excluded_urls(ledger_path)
            reprocessing = name in processed_names
            if reprocessing:
                jd_result["reprocess"] = True
            allowed_urls = set()
            if reprocessing:
                allowed_urls = ledger.prior_own_urls(
                    ledger_path, name, jd_title=profile.get("title"))

            # Track cumulative metrics across iterations
            all_discovered = []
            total_scored_this_jd = 0
            total_scored_cap = int(cfg["scoring"].get("max_scored_per_jd_per_run", 0) or 0)

            # ---- Iteration loop (bounded by max_passes and time budget) ----
            for iteration_num in range(1, max_passes + 1):
                elapsed = time.time() - run_start_time
                if elapsed > time_budget_minutes * 60:
                    break

                # Track what's discovered before this iteration
                prev_discovered_count = len(all_discovered)

                records, errors = xray.run_track_a(profile, cfg=cfg,
                                                   queries=plan_batch)
                p_recs, p_errors = portfolio.run_portfolio_discovery(profile, cfg)
                records += p_recs
                records += exported_records
                errors += p_errors

                if errors and iteration_num == 1:
                    jd_result.setdefault("notes", []).extend(errors[:2])

                # Dedup against cumulative known records + ledger
                records = dedup.apply_dedup(records, rows, cfg,
                                            allowed_urls=allowed_urls, jd_key=name)
                records = [r for r in records if r.get("dedup_status") != "duplicate"]

                # pre-scoring exclusion skip
                records, reg_skipped = exclusions.split_records(records, registry_urls)
                if reg_skipped and iteration_num == 1:
                    jd_result["exclusion_skipped"] = len(reg_skipped)

                survivors, eliminated = score_filters.apply_hard_filters(
                    records, profile, cfg)

                if survivors:
                    # Respect per-JD scoring cap across all iterations
                    space_left = max(0, total_scored_cap - total_scored_this_jd) if total_scored_cap else len(survivors)
                    if space_left <= 0:
                        break  # Cap reached; stop iterating

                    if space_left < len(survivors):
                        jd_result.setdefault("score_cap_deferred", 0)
                        jd_result["score_cap_deferred"] += len(survivors) - space_left
                        survivors = survivors[:space_left]

                    scored = []
                    for rec in survivors:
                        try:
                            s = scoring.score_candidate(profile, rec, _scoring_llm())
                            scored.append({**rec, **s})
                        except Exception as exc:
                            jd_result.setdefault("score_errors", []).append(str(exc)[:80])

                    scoring.save_scores(profile.get("title") or name, scored)
                    all_discovered.extend(scored)
                    total_scored_this_jd += len(scored)

                    # register zero-score candidates
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

                jd_result["iterations"] = iteration_num

                # Early exit: zero new candidates in this iteration
                if len(all_discovered) == prev_discovered_count:
                    break

            # After all iterations, select top N and append to ledger
            jd_result["discovered"] = len(all_discovered)
            jd_result["filtered"] = jd_result.get("discovered", 0) - len(all_discovered)
            jd_result["scored"] = len(all_discovered)

            if all_discovered:
                picked = topn.select_top_n(
                    all_discovered, excluded_urls=excluded,
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

    # ---- Delivery stage (email ledger) ----
    ledger_size_after = ledger_path.stat().st_size if ledger_path.exists() else 0
    delivery_status = None
    # Send ledger if: (1) enabled, (2) file exists, and (3) either changed or explicitly requested
    delivery_enabled = cfg.get("delivery", {}).get("enabled", True)
    if delivery_enabled and ledger_path.exists():
        try:
            from gmail_delivery import send_ledger_email
            recipient = os.environ.get("SOURCING_EMAIL_RECIPIENT") or cfg.get("delivery", {}).get("recipient", "sidharthrkc@gmail.com")
            send_ledger_email(ledger_path, recipient)
            delivery_status = "ok"
            summary["ledger_delivered"] = True
        except Exception as exc:
            delivery_status = f"failed ({str(exc)[:60]})"
            summary["ledger_delivered"] = False
            summary.setdefault("delivery_error", str(exc)[:120])

    return summary


def main() -> int:
    print(json.dumps(run(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
