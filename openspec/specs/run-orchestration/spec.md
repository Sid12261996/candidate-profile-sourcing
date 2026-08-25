# run-orchestration Specification

## Purpose

Wires the pipeline together as one daily unattended Hermes workflow: cron scheduling, stage sequencing, notifications, dashboard manageability, and deployment constraints (local-first, cloud-portable, account-safe).

## Requirements

### Requirement: Daily scheduled run
The workflow SHALL execute once per day on a schedule managed by Hermes' built-in cron scheduler, in a fresh agent session with the sourcing skill attached, and SHALL be creatable, pausable, editable, and triggerable from both the Hermes web dashboard and natural-language chat.

#### Scenario: Cron fires with work pending
- **WHEN** the scheduled time arrives with JDs or exports waiting
- **THEN** a run executes end-to-end without human intervention

#### Scenario: Human manages the job via dashboard
- **WHEN** an operator opens the Hermes web dashboard's Cron page
- **THEN** the sourcing job is listed with its state and last/next run times and can be paused, edited, or triggered manually

### Requirement: Stage sequencing with per-JD isolation
Each run SHALL process stages in order - intake, discovery, evaluation, ledger update - and SHALL isolate failures per JD so that an error processing one job description does not prevent other JDs from completing.

#### Scenario: One bad search query
- **WHEN** Track A queries fail for one JD but succeed for another in the same run
- **THEN** the second JD still produces shortlist rows and only the first is reported as partially failed

### Requirement: Run notification
Every run SHALL deliver a summary to the operator's configured channel stating per-JD results (candidates discovered, scored, added), any deferred or failed steps, and files quarantined; runs where nothing was processed MAY stay silent.

#### Scenario: Productive run notifies
- **WHEN** a run adds candidates for two JDs and fails to ingest one export file
- **THEN** the notification lists both additions plus the failed file and reason

#### Scenario: Idle run stays quiet
- **WHEN** no pending JDs and no inbox exports exist at fire time
- **THEN** no notification is sent

### Requirement: Local-first, cloud-portable configuration
All workflow configuration - storage backend selection, folder paths, model pinning, schedules, search backend endpoints, ledger location - SHALL live in config files within this repository (plus Hermes' own config), MUST NOT embed machine-specific absolute paths or secrets in code, and MUST be restorable onto a fresh machine or cloud host from the repo plus documented setup steps.

#### Scenario: Migration rehearsal
- **WHEN** an operator clones the repository to a new host, installs Hermes, restores credentials, and follows the documented setup
- **THEN** the next scheduled run behaves identically to the original machine

### Requirement: One-command local environment bring-up
The repository SHALL provide a `run-local.sh` script that, on a machine with only Docker installed, brings up the complete local system - external services defined in Docker Compose (search backend) and the Hermes runtime container (gateway, cron scheduler, web dashboard) - including skill sync into the Hermes home volume and sourcing-cron-job registration; repeated invocations MUST be idempotent.

#### Scenario: Clean machine bring-up
- **WHEN** an operator with Docker installed but no prior configuration clones the repository and runs `./run-local.sh`
- **THEN** the Compose stack builds and reports healthy, the sourcing skill is present in the Hermes runtime, the cron job exists in paused state, and the dashboard answers at localhost:9119

#### Scenario: Re-run preserves state
- **WHEN** `run-local.sh` executes again on an already-configured machine
- **THEN** existing credentials, cron jobs, and session data are preserved and no duplicate cron job or service is created

#### Scenario: Missing credentials fail soft
- **WHEN** required credentials are absent at startup (LLM provider key always; storage credentials only when the `gdrive` backend is enabled)
- **THEN** services still start, the script names exactly which credentials are missing and where to place them, and the cron job remains paused

### Requirement: Credential hygiene
The system SHALL keep all secrets (remote-storage credentials when the `gdrive` backend is enabled, search API keys if any) out of the repository and out of logs; automation MUST NOT require LinkedIn or Naukri credentials to exist anywhere in the deployment.

#### Scenario: Repository audit
- **WHEN** the repository contents are inspected
- **THEN** no credential material is present and no log output contains secret values

### Requirement: Cost-bounded operation
During the experiment phase, the workflow SHALL operate without paid services beyond existing personal subscriptions and free tiers: discovery uses free/public sources, LLM calls are bounded by the hard-filter-first design, and the Hermes cron job SHALL pin an explicit model/provider so runs cannot silently inherit costlier defaults.

#### Scenario: Model pin survives global change
- **WHEN** the operator changes their interactive chat model in Hermes
- **THEN** subsequent scheduled sourcing runs still use the pinned model configured for the job
