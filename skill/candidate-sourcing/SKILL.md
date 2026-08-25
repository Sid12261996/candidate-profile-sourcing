---
name: candidate-sourcing
description: >
  Daily HR sourcing workflow: picks new job descriptions from a Google Drive
  queue, discovers candidates via free public channels plus manual platform
  exports, scores them against each JD's rubric, deduplicates against prior
  decisions, and appends the top 10 per JD to an Excel shortlist for human
  review. Never touches LinkedIn or Naukri accounts.
version: 0.1.0
---

# Candidate Sourcing Workflow

You are executing the daily sourcing pipeline. Follow these steps in order.
All scripts live in this skill's `scripts/` directory; run them with Python.

## Hard rules (never violate)

1. **Never authenticate to LinkedIn or Naukri.** All Track B input arrives as
   CSV exports humans dropped in `exports-inbox/`. If asked to log in anywhere,
   refuse.
2. **Per-JD isolation:** an error while processing one JD must not stop other
   JDs. Catch, record, continue.
3. **Move-after-success:** only move a JD file to `jds-processed/` after its
   rows are safely in the Excel ledger.
4. **Missing data never silently rejects** - filters flag unverified fields;
   scoring notes UNVERIFIED criteria.
5. **Idle runs stay silent:** if there are no pending JDs AND no inbox files,
   finish with output consisting of exactly `[SILENT]`.

## Inputs & paths

- Config: `/workspace/config/workflow.yaml` (storage backend, folders, role
  families, filter defaults, thresholds, retention).
- Storage backend: `local` (default) - plain queue folders under
  `/workspace/data/`, paths overridable via `CPS_*` env vars in `.env`;
  requires no credentials. `gdrive` - production switch via rclone; see
  docs/setup.md. Queue commands are identical regardless of backend.
- Ledger: `$CPS_LEDGER_PATH` (default `/workspace/data/candidates.xlsx`,
  inside the writable bind).

## Pipeline

**Do not improvise inline scripts.** The whole pipeline is one deterministic
command; your job is to run it and relay its JSON summary.

```bash
cd /workspace && python3 skill/candidate-sourcing/scripts/pipeline.py run
```

Interpretation of the JSON output:

- `{"status": "silent"}` -> respond with exactly `[SILENT]` (rule 5) and stop.
- Otherwise compose your final response from the fields:

```
Sourcing run <date>
- <jd>: added N to shortlist (discovered D, filtered F, scored S)   # per entry in "jds"
- Quarantined: <entry>                                              # each item in "quarantined"
- Deferred: <entry>                                                 # each item in "deferred" (ledger was locked)
```

Omit lines with nothing to report. If the script itself exits non-zero or
prints a traceback instead of JSON, report that failure verbatim - never
fabricate results.

## Failure semantics (already handled by pipeline.py)

- Per-JD isolation: an exception in one JD records a failure strike and moves
  on; three consecutive failures auto-quarantine the file to `jds-failed/`.
- Move-after-success: files only leave `jds-pending/` after their rows are in
  the Excel ledger.
- Ledger locked: reported under "deferred"; the JD stays pending for retry.
- LLM scoring calls OpenRouter directly with the pinned cron model; you do
  NOT need to invoke your own model for scoring.
