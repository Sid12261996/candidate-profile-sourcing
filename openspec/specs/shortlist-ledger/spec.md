# shortlist-ledger Specification

## Purpose

Owns the Excel file that serves as both the human-facing deliverable and the workflow's memory: append-only candidate rows with a reviewer-controlled status column that drives exclusion of already-seen or rejected candidates.

## Requirements

### Requirement: Ledger schema
The shortlist ledger SHALL be a single Excel workbook with one row per candidate per JD containing at minimum: date added, JD identifier/title, candidate name, title/headline, current company, location, source track, profile URL(s), score (0-100), score justification, status, and notes.

#### Scenario: Fresh workbook
- **WHEN** no ledger file exists at first run
- **THEN** the workbook is created with the required columns and header formatting

### Requirement: Append-only new entries
Newly selected candidates SHALL be appended as new rows with status initialized to `new`; existing rows MUST NOT be modified by the workflow.

#### Scenario: Run adds candidates
- **WHEN** a run selects 10 candidates for a JD
- **THEN** 10 rows appear with status `new`, today's date, their scores and justifications, and no previously existing row's content changed

### Requirement: Status-driven exclusion
The system SHALL exclude from future shortlists any ledger candidate whose status was set by the human reviewer to a terminal value - at minimum `rejected`, and also `contacted`, `interviewing`, `hired` - treating `new` as the only value eligible for re-shortlisting consideration.

#### Scenario: Reviewer rejects a candidate
- **WHEN** a stakeholder sets a row's status to `rejected` and subsequent runs execute
- **THEN** that candidate never appears in a new top-10 list for any JD

#### Scenario: Reviewer marks contacted
- **WHEN** a stakeholder sets a row's status to `contacted`
- **THEN** the candidate is not re-shortlisted while that status stands

### Requirement: Ledger integrity on write
The system SHALL preserve the ledger against partial writes by backing up the workbook before each modification and refusing to write when the file is locked/open in Excel.

#### Scenario: File open in Excel during run
- **WHEN** the daily run attempts to update the ledger but the workbook is locked by another program
- **THEN** the run completes all other work, reports the ledger update as deferred, and retries it on the next scheduled run

#### Scenario: Corrupt write prevented
- **WHEN** a write is interrupted mid-save
- **THEN** the pre-write backup remains available and the ledger can be restored from it
