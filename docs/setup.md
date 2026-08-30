# Setup — candidate-profile-sourcing

Local-first HR sourcing stack: a Hermes Agent runtime plus a SearXNG search service, both under Docker Compose, driven by one script.

## Prerequisites

- **Docker Desktop** (or any Docker Engine + Compose v2). This is the only host prerequisite.
  - macOS: give the VM at least 4 GB RAM (gateway + dashboard are modest, but Python images add up).
- A Google Cloud project (for Drive access) — see *Google Drive credentials* below.
- An LLM provider API key accepted by Hermes (OpenRouter, Anthropic, OpenAI, Nous Portal, …).
- **Claude API key** (`$CLAUDE_API_KEY`) for search and query-expansion tasks — see *Claude API key* below.

## Quickstart

```bash
./run-local.sh
```

What it does, in order:

1. Prechecks Docker and Compose.
2. Bootstraps `.env` from `.env.example` — **never overwrites** an existing `.env`.
3. `docker compose up -d --build` for the `hermes` and `searxng` services.
4. Waits for both health checks.
5. Syncs `skill/candidate-sourcing/` into the Hermes home volume.
6. Registers the daily sourcing **cron job in paused state** (skipped if it already exists).
7. Prints the dashboard URL (`http://localhost:9119`) and what's still missing, if anything.

Re-running is always safe; existing credentials, cron jobs, and session history are preserved.

## Credentials (all outside git)

| Secret | Where | How |
|---|---|---|
| LLM provider key | `.env` (repo root, gitignored) | Copy value from your provider dashboard; used for scoring rubric calls |
| Claude API key | `.env` (repo root, gitignored) | Copy from Anthropic Console; used for search and query-expansion tasks |
| Google service-account JSON | mounted into the Hermes home volume | See below |
| Gmail OAuth | Hermes runtime (automatic on first use) | See below |
| rclone remote config | inside the Hermes home volume | See below |

There must be **no LinkedIn or Naukri credentials anywhere** in this deployment — by design.

### LLM provider key

```bash
cp .env.example .env      # first time only
$EDITOR .env              # fill in your provider key(s)
```

### Claude API key

The pipeline uses Claude (via the Anthropic API) for query-expansion planning and Track A profile search:

1. Obtain an API key from [Anthropic Console](https://console.anthropic.com/account/keys).
2. Add it to `.env`:

```bash
$EDITOR .env              # add CLAUDE_API_KEY=<your-key>
```

### Gmail authorization

After startup, Gmail credentials are auto-provisioned by Hermes' OAuth flow on first ledger-delivery attempt. No manual setup required; Hermes handles the browser redirect automatically.

### Google Drive credentials (production switch only - NOT needed for testing)

Testing runs entirely on **local queue folders** under `data/` (override via
`CPS_*` variables in `.env`; see `.env.example`). Google Drive is the dormant
`gdrive` backend. To switch production on later:

1. In Google Cloud Console: create a **service account**, enable the **Drive API**, create a JSON key.
2. In Drive, share the three HR folders (`jds-pending`, `jds-processed`/`jds-failed` parent, `exports-inbox`) with the service account's email (editor access).
3. Put the JSON where the container can read it:

```bash
./run-local.sh cp-key ~/Downloads/hr-drive-sa.json   # helper copies into the volume
```

4. Configure the rclone remote inside the container:

```bash
docker compose exec hermes rclone config create hr-drive drive \
  scope=drive service_account_file=/hermes-home/secrets/hr-drive-sa.json
docker compose exec hermes rclone lsd hr-drive:     # should list the shared folders
```

5. Set `storage.backend: gdrive` in `config/workflow.yaml` and re-run `./run-local.sh`.

## First run checklist

1. `./run-local.sh` → all green, cron job listed as paused.
2. Fill `.env` with an LLM key → re-run `./run-local.sh` → it reports zero missing credentials.
3. Open `http://localhost:9119` → Cron page → trigger the sourcing job manually with a test JD in `jds-pending/`.

## Troubleshooting

_(filled in as implementation tasks complete — see tasks.md groups 9–10)_

<!-- TODO(9.x): chat smoke-test instructions -->

### Secret audit

Run any time (and before every push):

```bash
.venv/bin/python skill/candidate-sourcing/scripts/secret_audit.py   # exit 0 = clean
```

## Migration to another machine / cloud VPS

1. Clone this repo on the new host.
2. Copy `.env` and the service-account JSON (out-of-band; never via git).
3. `./run-local.sh`. Same command, same stack.
