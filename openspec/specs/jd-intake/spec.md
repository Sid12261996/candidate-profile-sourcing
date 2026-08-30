# jd-intake Specification

## Purpose

Manages the file-based JD queue that feeds job descriptions into the sourcing workflow - local folders by default, Google Drive as an alternative backend behind the same contract - turning dropped-in JD documents into structured requirement profiles and tracking which JDs have been processed.

## Requirements

### Requirement: Storage backend selection via environment
The queue SHALL operate over backend-selected folders: the `local` backend (default) resolves folders from environment variables (`CPS_JDS_PENDING_DIR`, `CPS_JDS_PROCESSED_DIR`, `CPS_JDS_FAILED_DIR`, `CPS_EXPORTS_INBOX_DIR`) with sane defaults under `data/`, requiring no network access or external credentials; the `gdrive` backend addresses the same folder names via rclone. Switching backends MUST NOT change queue semantics, and an unknown backend name MUST fail fast with a clear error.

#### Scenario: Local mode needs no external setup
- **WHEN** the workflow runs with the default `local` backend on a fresh machine
- **THEN** queue operations touch only configured local directories and make no network calls

#### Scenario: Unknown backend fails fast
- **WHEN** storage backend is set to an unrecognized value
- **THEN** startup aborts immediately naming the invalid value and valid options

### Requirement: Detect pending job descriptions
The system SHALL detect every JD document placed in the configured pending folder at the start of each run, treating each document as one open role instance.

#### Scenario: New JD appears between runs
- **WHEN** a user adds `workspace-designer-lead.md` to the pending folder and the next daily run starts
- **THEN** the run discovers the file and processes it as an open role in that same run

#### Scenario: Empty queue
- **WHEN** the pending folder contains no documents at run start
- **THEN** no JD processing occurs for the intake stage and the absence is reflected in the run summary

#### Scenario: Re-added JD after successful processing
- **WHEN** a JD filename already exists in the processed folder and is re-added to the pending folder
- **THEN** the run detects this JD as re-processable and does not silently suppress all results via dedup; prior non-terminal ledger rows for this JD no longer suppress new selections

### Requirement: Parse JD into a requirement profile
The system SHALL convert each JD document into a structured requirement profile containing at minimum: role title, role family, seniority level, must-have skills/experience, preferred skills, experience band in years, location constraints (city/remote), and any scoring weights or specifics stated in the description.

#### Scenario: Fully specified JD
- **WHEN** a JD states role title, 6+ years experience, Mumbai-based, and weights design portfolio quality highest
- **THEN** the resulting requirement profile carries all of those fields and the scoring stage can consume them without re-reading the raw text

#### Scenario: Partially specified JD
- **WHEN** a JD omits a field (e.g., no explicit experience band)
- **THEN** the profile records that field as unspecified rather than inventing a value, and defaults documented in the workflow config apply

#### Scenario: Re-added JD re-parsing
- **WHEN** a re-added JD is parsed again
- **THEN** the profile is rebuilt from the raw text and tracking updates to reflect re-processing

### Requirement: Move processed JDs out of the queue
The system SHALL move a JD file from the pending folder to the processed folder only after its full pipeline (intake through ledger update for that JD) completes successfully within the run.

#### Scenario: Successful processing
- **WHEN** a JD's candidates have been scored and written to the shortlist ledger
- **THEN** the JD file is present in the processed folder and absent from the pending folder

#### Scenario: Run fails mid-processing
- **WHEN** the run errors out while processing a JD (e.g., search backend unavailable)
- **THEN** the JD file remains in the pending folder so the next scheduled run retries it

#### Scenario: Re-added JD processing
- **WHEN** a re-added JD completes its pipeline
- **THEN** the JD file is moved to processed and new candidates are appended to the ledger with prior non-terminal rows relaxed

### Requirement: Quarantine repeatedly failing JDs
The system SHALL move a JD file to the failed folder once it has failed processing on 3 consecutive runs, recording the failure reason in the run notification.

#### Scenario: Persistently malformed JD
- **WHEN** a JD cannot be parsed on three consecutive daily runs
- **THEN** the file is moved to the failed folder and the run notification names the file and the reason, and subsequent runs no longer attempt it

#### Scenario: Re-added JD after quarantine
- **WHEN** a previously quarantined JD is re-added to pending
- **THEN** it is treated as a new JD and processed fresh
