## Context

See proposal.md - Why. Relevant current state: `skill/candidate-sourcing/scripts/pipeline.py` runs one discovery→evaluation pass per JD per run; `config/workflow.yaml` has no delivery or iteration-budget config; LLM calls (`expansion` stage, Track A agent search) currently assume OpenRouter-style config without a pinned Claude credential; the ledger lives at `$CPS_LEDGER_PATH` (default `/workspace/data/candidates.xlsx`) with no outbound notification of its contents beyond the text run summary.

## Goals / Non-Goals

**Goals:**
- Deliver the ledger file itself (not just a text summary) to `sidharthrkc@gmail.com` after productive runs.
- Let a single cron fire keep discovering for a JD across several iterations instead of stopping at one pass, within a bounded budget.
- Make `$CLAUDE_API_KEY` the credential path for Hermes-agent-driven search and expansion-plan LLM calls.

**Non-Goals:**
- Changing the cron *schedule* (daily cadence stays as-is; only per-fire depth changes).
- Building a general-purpose email/notification framework beyond this one ledger-delivery use case.
- Migrating scoring LLM calls (which already go to OpenRouter per `SKILL.md`) - only expansion planning and Track A agent search calls move to `$CLAUDE_API_KEY`. If the operator wants scoring migrated too, that's a separate change.

## Decisions

**Delivery mechanism: Hermes Gmail integration over raw SMTP.**
Hermes already exposes a Gmail MCP-style integration for the agent (see the `mcp__claude_ai_Gmail__*` tool family used in agent sessions); using it avoids storing SMTP credentials in the deployment and reuses the same OAuth the operator already grants Hermes. Alternative considered: SMTP with an app password stored in `.hermes/secrets/` - rejected because it adds a second credential type for one recipient when Gmail access may already be authorized.

**Delivery trigger: after ledger write, before final notification.**
The pipeline step order becomes intake → discovery/evaluation (iterated) → ledger update → email delivery → text notification. Attaching delivery before the text summary lets the summary report delivery success/failure inline (per candidate-delivery spec's failure-reporting requirement).

**Iteration control: fixed max-iterations + time budget, configured per role family or globally in `workflow.yaml`.**
A new `iteration` config block (e.g. `iteration.max_passes: 3`, `iteration.time_budget_minutes: 20`) governs the loop in `pipeline.py`. Alternative considered: iterate until `max_scored_per_jd_per_run` (150) is hit - rejected as the sole stop condition because a JD with a small candidate pool would loop uselessly until the cap; zero-new-candidates-this-iteration is kept as an early-exit condition alongside the caps.

**Claude credential wiring: environment variable only, no new secrets file.**
`$CLAUDE_API_KEY` is read directly from the Hermes runtime environment (same mechanism already used for other required credentials per the existing "Missing credentials fail soft" requirement in run-orchestration). No new secret-storage path is introduced.

## Risks / Trade-offs

- [Larger attachments could hit Gmail size limits as the ledger grows] → Mitigation: candidate-delivery spec explicitly makes delivery failure non-fatal to the run; a future change can add ledger-size trimming or archival if this triggers in practice.
- [Multi-pass iteration increases run duration and LLM/search call volume per fire] → Mitigation: bounded by `max_passes` and `time_budget_minutes`, and existing `max_scored_per_jd_per_run` / `max_queries_per_jd_per_run` caps in `workflow.yaml` still apply per JD regardless of iteration count.
- [Splitting LLM credentials across two providers (OpenRouter for scoring, Claude for expansion/search) adds operational complexity] → Mitigation: scoped explicitly as a Non-Goal to only migrate what the user requested; documented in `docs/setup.md` so the split is not mistaken for an oversight.

## Migration Plan

1. Add `delivery`, `iteration`, and Claude credential config sections to `config/workflow.yaml` with safe defaults (delivery recipient fixed to `sidharthrkc@gmail.com` per requirement; `max_passes` defaulting low, e.g. 3).
2. Implement the iteration loop and delivery step in `pipeline.py`; keep both behind the existing per-JD isolation and move-after-success guarantees.
3. Update `docs/setup.md` with `$CLAUDE_API_KEY` provisioning and Gmail authorization steps.
4. Roll out on the existing paused-by-default cron job; no schema migration needed since only new optional config keys are added (rollback = revert config + code, ledger format unchanged).
