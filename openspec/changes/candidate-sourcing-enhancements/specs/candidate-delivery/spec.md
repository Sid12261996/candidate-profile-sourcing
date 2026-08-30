## Purpose

Delivers the current candidate shortlist ledger to the operator's inbox via Gmail after a run, so results reach a human without them opening the workspace or dashboard.

## ADDED Requirements

### Requirement: Ledger emailed after productive runs
After a run that adds one or more rows to the Excel ledger, the system SHALL send an email via Gmail to `sidharthrkc@gmail.com` with the current `candidates.xlsx` file attached.

#### Scenario: Run adds candidates
- **WHEN** a run appends new rows to the ledger for at least one JD
- **THEN** an email is sent to `sidharthrkc@gmail.com` with the current `candidates.xlsx` attached after the ledger write completes

#### Scenario: Idle or no-op run
- **WHEN** a run makes no changes to the ledger (idle run, or all JDs deferred/failed before any write)
- **THEN** no email is sent

### Requirement: Delivery failure does not fail the run
A failure to send the delivery email (Gmail auth failure, attachment size limit, transient API error) SHALL be recorded in the run notification as a delivery failure and MUST NOT be treated as a pipeline failure or block ledger updates already made.

#### Scenario: Gmail send fails
- **WHEN** the Gmail send call errors after the ledger has been successfully updated
- **THEN** the run still reports its normal per-JD results, plus a line noting the ledger email failed to send and why

### Requirement: Idempotent delivery
The system SHALL NOT send more than one delivery email per run, and MUST NOT re-send the ledger for a run that already delivered it successfully (e.g., on manual re-trigger of notification logic).

#### Scenario: Re-triggered notification step
- **WHEN** the notification step for an already-completed run is invoked again without new ledger changes
- **THEN** no duplicate delivery email is sent
