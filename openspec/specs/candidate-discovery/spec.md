# candidate-discovery Specification

## Purpose

Produces a normalized pool of candidate records for each open JD using two tracks: free automated discovery over public web sources, and ingestion of CSV exports that stakeholders generate manually from premium platforms.

## Requirements

### Requirement: Track A public x-ray discovery
For each processed JD, the system SHALL run search queries against public professional profiles via general search engines (e.g., `site:linkedin.com/in "<role title>" <city>` variants derived from the requirement profile) without authenticating to any platform, collecting name, headline, location, and profile URL where the search results expose them.

#### Scenario: X-ray query yields candidates
- **WHEN** Track A runs for a "Client Success Officer" JD targeting Mumbai
- **THEN** candidate records are produced from public search results matching role and location terms, each carrying whatever public fields the result exposed

#### Scenario: Search backend unavailable
- **WHEN** the configured search backend fails or returns errors during Track A
- **THEN** Track A contributes zero candidates for that JD, the failure is noted in the run summary, and the run continues with other sources

### Requirement: Track A portfolio discovery for design roles
For JDs whose role family is design (workspace designer, graphic designer), the system SHALL additionally query public portfolio sources (Behance, Dribbble) restricted to India-based creators where such filtering is supported by the source.

#### Scenario: Design JD triggers portfolio search
- **WHEN** the requirement profile has role family "design"
- **THEN** portfolio-source results are merged into the same candidate pool alongside x-ray results

#### Scenario: Non-design JD skips portfolios
- **WHEN** the requirement profile has role family "business development" or "client success"
- **THEN** no portfolio-source queries are made for that JD

### Requirement: Track B ingestion of manual exports
The system SHALL ingest every CSV/Excel file found in the configured `exports-inbox/` folder of the active storage backend at run start, mapping its columns into the normalized candidate schema, and SHALL remove each ingested file from `exports-inbox/` after successful ingestion (moving it to `jds-processed/` alongside JDs or an equivalent archive).

#### Scenario: Recruiter export dropped in inbox
- **WHEN** a stakeholder exports LinkedIn Recruiter search results as CSV and places the file in `exports-inbox/`
- **THEN** the next run ingests every row as candidate records tagged with source `recruiter-export`

#### Scenario: Unrecognized export format
- **WHEN** a file in `exports-inbox/` cannot be mapped to the candidate schema (unknown columns, corrupt file)
- **THEN** it is moved to `jds-failed/`, named in the run notification, and does not block processing of other inbox files

### Requirement: Candidate record normalization
Every discovered candidate SHALL be represented as a single normalized record containing at minimum: full name (as available), current title/headline, current company (if known), location, experience indicators (years where derivable), source track (`xray`, `portfolio`, or `platform-export`), source-specific profile URL(s), and the JD it was surfaced for.

#### Scenario: Same person from two tracks in one run
- **WHEN** x-ray search and a ResDEX export both surface a candidate matching the dedup rules for one JD
- **THEN** they merge into one record with both source references retained

### Requirement: No authenticated platform access
The system MUST NOT store or use LinkedIn or Naukri credentials, authenticate to those platforms, or automate any session against them; all interaction with premium platforms is limited to parsing files humans exported through the platforms' own UIs.

#### Scenario: Audit of automation surface
- **WHEN** the workflow executes any stage
- **THEN** no network request carries LinkedIn or Naukri authentication material

## MODIFIED Requirements

### Requirement: Track A public x-ray discovery
For each processed JD, the system SHALL run search queries against public professional profiles via general search engines (e.g., `site:linkedin.com/in "<role title>" <city>` variants derived from the requirement profile) without authenticating to any platform, collecting name, headline, location, and profile URL where the search results expose them.

#### Scenario: X-ray query yields candidates
- **WHEN** Track A runs for a "Client Success Officer" JD targeting Mumbai
- **THEN** candidate records are produced from public search results matching role and location terms, each carrying whatever public fields the result exposed

#### Scenario: Search backend unavailable
- **WHEN** the configured search backend fails or returns errors during Track A
- **THEN** Track A contributes zero candidates for that JD, the failure is noted in the run summary, and the run continues with other sources

#### Scenario: India-scoped x-ray queries
- **WHEN** Track A runs for a JD with India location constraints
- **THEN** every query appended with India-scoping terms (city names + "India") to enforce geography

### Requirement: Track A portfolio discovery for design roles
For JDs whose role family is design (workspace designer, graphic designer), the system SHALL additionally query public portfolio sources (Behance, Dribbble) restricted to India-based creators where such filtering is supported by the source.

#### Scenario: Design JD triggers portfolio search
- **WHEN** the requirement profile has role family "design"
- **THEN** portfolio-source results are merged into the same candidate pool alongside x-ray results

#### Scenario: Non-design JD skips portfolios
- **WHEN** the requirement profile has role family "business development" or "client success"
- **THEN** no portfolio-source queries are made for that JD

### Requirement: India-scoped portfolio discovery
For JDs whose role family is design, the system SHALL additionally query public portfolio sources restricted to India-based creators, with India scoping terms appended to every query.

#### Scenario: Design JD with India portfolio search
- **WHEN** the requirement profile has role family "design" and India location constraints
- **THEN** portfolio-source results are merged with India-scoped queries only

### Requirement: LLM-generated expansion plan
Before discovery, the system SHALL generate an LLM plan producing 200–500 query combinations across title variants, skills, tools, seniority, and on-site cities, validated against min/max bounds, case-insensitive dedupe, and India-scope enforcement. The LLM call SHALL authenticate using the API key exposed via the `$CLAUDE_API_KEY` environment variable.

#### Scenario: Expansion plan validation
- **WHEN** the expansion plan is generated
- **THEN** it is stripped of case-insensitive duplicates, dropped if lacking India scoping terms, and bounded by `expansion.min_combinations: 200` / `max_combinations: 500`

#### Scenario: Deterministic template fallback
- **WHEN** the LLM plan is empty or fails validation
- **THEN** a deterministic template fallback runs (role-patterns × cities × top skills) with a summary note, and the plan file records the fallback trigger

### Requirement: Plan persisted and resumed
The validated expansion plan persists at `data/state/query-plans/<jd>.json`. Execution consumes up to `search_backend.max_queries_per_jd_per_run` per run and resumes the remainder on the next run.

#### Scenario: Partial plan resume
- **WHEN** a previous run consumed some queries from the plan and the next run starts
- **THEN** the system resumes from where it stopped, consuming the remaining queries up to the per-run budget
