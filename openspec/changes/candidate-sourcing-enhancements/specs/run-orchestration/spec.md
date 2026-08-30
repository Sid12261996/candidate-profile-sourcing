## MODIFIED Requirements

### Requirement: Stage sequencing with per-JD isolation
Each run SHALL process stages in order - intake, discovery, evaluation, ledger update - and SHALL isolate failures per JD so that an error processing one job description does not prevent other JDs from completing. For each JD, the discovery-through-evaluation stages SHALL repeat in successive iterations within the same run, each iteration attempting to surface additional not-yet-seen candidates, until either a configured maximum iteration count is reached, a configured per-run time budget is exhausted, or an iteration yields zero new candidates for that JD.

#### Scenario: One bad search query
- **WHEN** Track A queries fail for one JD but succeed for another in the same run
- **THEN** the second JD still produces shortlist rows and only the first is reported as partially failed

#### Scenario: Multiple iterations surface more candidates
- **WHEN** a JD's first discovery iteration yields new candidates and the configured max iterations has not been reached
- **THEN** the pipeline runs another discovery-through-evaluation iteration for that JD before moving to ledger update, seeking additional candidates not already collected in this run

#### Scenario: Iteration budget exhausted
- **WHEN** a JD reaches the configured max iterations, or the run's time budget elapses, or an iteration returns zero new candidates
- **THEN** iteration for that JD stops and the JD proceeds to ledger update with whatever candidates were collected across its iterations

### Requirement: Run notification
Every run SHALL deliver a summary to the operator's configured channel stating per-JD results (candidates discovered, scored, added, and number of discovery iterations performed), any deferred or failed steps, and files quarantined; runs where nothing was processed MAY stay silent.

#### Scenario: Productive run notifies
- **WHEN** a run adds candidates for two JDs and fails to ingest one export file
- **THEN** the notification lists both additions plus the failed file and reason, including how many iterations each JD ran

#### Scenario: Idle run stays quiet
- **WHEN** no pending JDs and no inbox exports exist at fire time
- **THEN** no notification is sent
