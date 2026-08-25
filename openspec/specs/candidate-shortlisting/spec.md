# candidate-shortlisting Specification

## Purpose

Turns the raw candidate pool for each JD into a ranked shortlist: cheap deterministic filters first, LLM rubric scoring on survivors, duplicate suppression against prior decisions, and top-10 selection per JD per run.

## Requirements

### Requirement: Hard filters precede scoring
Before any LLM evaluation, the system SHALL apply deterministic hard filters derived from the requirement profile - location constraints and minimum experience band at minimum - and eliminate candidates failing them.

#### Scenario: Location mismatch eliminated cheaply
- **WHEN** a JD requires Bangalore-based candidates and a record's location resolves outside the accepted set
- **THEN** the record is excluded before rubric scoring and consumes no LLM tokens

#### Scenario: Missing data is not silently rejected
- **WHEN** a record lacks the field needed to evaluate a hard filter (e.g., no location)
- **THEN** the record passes through to scoring flagged as unverified rather than being dropped

### Requirement: Rubric scoring against the JD
Surviving candidates SHALL receive a score from 0-100 assigned by LLM evaluation against the JD's requirement profile, with each score accompanied by a short justification citing which must-have/preferred criteria the candidate meets or lacks.

#### Scenario: Strong match scores high with reasons
- **WHEN** a senior workspace designer record satisfies all must-haves and most preferred criteria of a lead JD
- **THEN** the record receives a high score and a justification naming the matched criteria

#### Scenario: Scores are reproducible artifacts
- **WHEN** scoring completes for a JD
- **THEN** every scored record's score and justification are persisted so later stages and audits can read them

### Requirement: Top-10 selection per JD per run
After scoring, the system SHALL select at most the 10 highest-scoring not-yet-excluded candidates per JD per run for delivery to the shortlist ledger.

#### Scenario: More than ten qualified candidates
- **WHEN** 40 candidates pass filters and receive scores above threshold
- **THEN** only the top 10 by score flow to the ledger for this run

#### Scenario: Fewer than ten qualified candidates
- **WHEN** only 4 candidates survive filtering and score above threshold
- **THEN** exactly those 4 flow to the ledger

### Requirement: Cross-run and cross-track duplicate suppression
The system SHALL identify candidates already present in the shortlist ledger (matched by exact profile URL when available, otherwise by fuzzy name plus employer similarity) and exclude them from new shortlists regardless of which track re-surfaces them.

#### Scenario: Previously shortlisted candidate re-found
- **WHEN** a candidate shortlisted last week appears again via a different source
- **THEN** they do not occupy a slot in this run's top 10

#### Scenario: Uncertain identity match is surfaced, not hidden
- **WHEN** a new record fuzzy-matches an existing ledger row but is not conclusively the same person
- **THEN** the record is flagged as possible-duplicate in the ledger entry instead of being silently skipped or silently duplicated
