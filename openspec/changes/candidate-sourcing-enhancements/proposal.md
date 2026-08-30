## Why

The sourcing pipeline currently leaves results sitting in a local Excel ledger that a human must manually retrieve, runs discovery only once per JD per day (capping how many candidates a single day's cron fire can surface), and depends on OpenRouter for LLM calls even though a Claude API key is already available to the deployment. Wiring in Gmail delivery, multi-pass discovery within a run, and native Claude-powered search closes these gaps without adding new infrastructure.

## What Changes

- Add a delivery step that emails the current `candidates.xlsx` ledger as an attachment to `sidharthrkc@gmail.com` via Gmail after each run that produced ledger updates.
- Change the cron-triggered run to repeat its discovery/scoring loop for a JD across multiple iterations within the same run (bounded by a configured max-iterations/time budget) instead of stopping after one pass, so each fire surfaces the largest candidate pool it can before quitting.
- Introduce `$CLAUDE_API_KEY` as the credential the Hermes agent uses for its own model calls when performing Track A profile search and query-expansion planning, replacing the implicit OpenRouter-only assumption for that stage.

## Capabilities

### New Capabilities
- `candidate-delivery`: Emailing the ledger file to a configured recipient via Gmail after a run, including failure handling and idempotency (don't re-send unchanged ledgers).

### Modified Capabilities
- `run-orchestration`: Stage sequencing changes from a single discovery/scoring pass per JD per run to a bounded multi-iteration loop that keeps expanding the candidate pool until a max-iterations or time budget is hit; run notification gains a per-JD iteration count.
- `candidate-discovery`: Track A search and the LLM-generated expansion plan SHALL authenticate using `$CLAUDE_API_KEY` rather than the prior implicit provider assumption; missing/invalid key is treated as a hard-filter-style failure for that stage (recorded, run continues).

## Impact

- Affected code: `skill/candidate-sourcing/scripts/pipeline.py` (iteration loop, delivery step), `config/workflow.yaml` (new `delivery` and iteration-budget sections, LLM provider/key config), Hermes cron job definition (unchanged trigger cadence, changed per-fire behavior).
- New dependency: Gmail send capability (Hermes/Google integration or SMTP) for delivery; `$CLAUDE_API_KEY` must be present in the Hermes runtime environment.
- Docs: `docs/setup.md` needs a note on provisioning `$CLAUDE_API_KEY` and Gmail credentials.
