## MODIFIED Requirements

### Requirement: LLM-generated expansion plan
Before discovery, the system SHALL generate an LLM plan producing 200–500 query combinations across title variants, skills, tools, seniority, and on-site cities, validated against min/max bounds, case-insensitive dedupe, and India-scope enforcement. The LLM call SHALL authenticate using the API key exposed via the `$CLAUDE_API_KEY` environment variable.

#### Scenario: Expansion plan validation
- **WHEN** the expansion plan is generated
- **THEN** it is stripped of case-insensitive duplicates, dropped if lacking India scoping terms, and bounded by `expansion.min_combinations: 200` / `max_combinations: 500`

#### Scenario: Deterministic template fallback
- **WHEN** the LLM plan is empty or fails validation
- **THEN** a deterministic template fallback runs (role-patterns × cities × top skills) with a summary note, and the plan file records the fallback trigger

#### Scenario: Missing or invalid Claude API key
- **WHEN** `$CLAUDE_API_KEY` is unset or the LLM call rejects it as invalid
- **THEN** the expansion stage records the failure, falls back to the deterministic template, and the run continues without halting other JDs

## ADDED Requirements

### Requirement: Hermes agent search uses the Claude API key
When the Hermes agent performs Track A profile search on behalf of a JD (query execution and any agent-driven result interpretation), it SHALL use the API key exposed via the `$CLAUDE_API_KEY` environment variable for its own model calls, rather than assuming a different provider is configured.

#### Scenario: Agent performs a search call
- **WHEN** the Hermes agent issues a Track A search backed by its own model call
- **THEN** the call authenticates using `$CLAUDE_API_KEY` from the runtime environment

#### Scenario: Key absent at startup
- **WHEN** the Hermes runtime starts without `$CLAUDE_API_KEY` set
- **THEN** the missing credential is reported the same way other required credentials are reported at startup, and Track A search calls that depend on it fail soft per-JD rather than crashing the run
