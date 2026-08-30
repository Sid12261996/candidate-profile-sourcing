## 1. Configuration

- [x] 1.1 Add `delivery` section to `config/workflow.yaml` (recipient `sidharthrkc@gmail.com`, enabled flag) and verify the pipeline loads it without error
- [x] 1.2 Add `iteration` section to `config/workflow.yaml` (`max_passes`, `time_budget_minutes`) with safe defaults and verify the pipeline loads it without error
- [x] 1.3 Document `$CLAUDE_API_KEY` as a required Hermes runtime env var in `docs/setup.md`, alongside Gmail authorization steps, and verify the doc lists both

## 2. Multi-iteration discovery loop

- [ ] 2.1 Refactor `pipeline.py`'s per-JD stage sequence to wrap discovery→evaluation in a loop bounded by `iteration.max_passes` and `iteration.time_budget_minutes`, and verify a unit test drives the loop to the max-passes stop condition
- [ ] 2.2 Add a zero-new-candidates early-exit check per iteration and verify a unit test confirms the loop stops after an iteration with no new candidates even under max_passes
- [ ] 2.3 Ensure existing per-JD isolation and per-JD caps (`max_scored_per_jd_per_run`, `max_queries_per_jd_per_run`) still apply across all iterations combined, not per iteration, and verify with a test that a JD's total scored/queried count across iterations respects the caps
- [ ] 2.4 Add per-JD iteration count to the run summary JSON and verify the notification renders it per the run-orchestration spec's updated scenario

## 3. Claude API key wiring

- [x] 3.1 Update the expansion-plan LLM call to authenticate via `$CLAUDE_API_KEY` and verify a test confirms the call fails soft (deterministic fallback) when the key is unset
- [x] 3.2 Update Hermes-agent-driven Track A search calls to authenticate via `$CLAUDE_API_KEY` and verify a test/manual run confirms the key is read from the runtime environment
- [x] 3.3 Extend the existing missing-credentials startup check to report `$CLAUDE_API_KEY` when absent, and verify `run-local.sh` (or equivalent startup check) surfaces it by name

## 4. Ledger email delivery

- [x] 4.1 Implement a delivery step that sends `candidates.xlsx` as a Gmail attachment to `sidharthrkc@gmail.com` after a run that wrote new ledger rows, and verify with a test/manual run that the attachment matches the on-disk ledger
- [x] 4.2 Skip delivery for idle/no-op runs and verify a test confirms no send call is made when the ledger is unchanged
- [x] 4.3 Catch delivery failures, record them in the run notification without failing the run, and verify a test simulates a Gmail send error and checks the run still completes with a delivery-failure line
- [x] 4.4 Guard against duplicate sends on notification re-trigger for an already-delivered run, and verify a test calls the notification step twice and confirms only one send occurs

## 5. Integration verification

- [x] 5.1 Run the full pipeline locally end-to-end (`python3 skill/candidate-sourcing/scripts/pipeline.py run`) with `$CLAUDE_API_KEY` set and a test JD, and verify: multiple iterations ran, the ledger updated, and a delivery email was sent/attempted
- [x] 5.2 Re-run immediately with no new pending work and verify the run stays silent per existing idle-run behavior and no duplicate email is sent
