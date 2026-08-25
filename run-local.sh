#!/bin/bash
# One-command local bring-up for the candidate sourcing stack (design D9).
# Idempotent: safe to re-run any time. Never prints or overwrites secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
COMPOSE_FILE="deploy/docker-compose.yml"
TIMEOUT_SECS=240

log()  { printf '\033[1;34m[run-local]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[run-local]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[run-local]\033[0m %s\n' "$*" >&2; exit 1; }

# Compose wrapper: interpolation values (${SEARXNG_SECRET:?} etc.) come from
# --env-file; the compose-level `env_file:` only injects into containers.
with_env() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

# cron list HIDES paused jobs -> jobs.json is the existence/pause source of truth
job_exists() {
  with_env exec -T hermes python3 -c "import json;d=json.load(open('/hermes-home/cron/jobs.json'));j=d.get('jobs',d);items=j.values() if isinstance(j,dict) else j;print(1 if any(x.get('name')=='$1' for x in items) else 0)" 2>/dev/null || echo 0
}
job_paused() {
  with_env exec -T hermes python3 -c "import json;d=json.load(open('/hermes-home/cron/jobs.json'));j=d.get('jobs',d);items=j.values() if isinstance(j,dict) else j;print(1 if any(x.get('name')=='$1' and not x.get('enabled',True) for x in items) else 0)" 2>/dev/null || echo 0
}

gen_secret() { openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

# Fill ONLY truly-empty values; user-provided values always win.
ensure_env_value() { # $1=key  $2=value-generator-command
  local key="$1" val
  val="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
  if [ -z "$val" ]; then
    val="$($2)"
    sed "s|^${key}=.*$|${key}=${val}|" "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    log "Generated a value for ${key}"
  fi
}

env_nonempty() { [ -n "$(grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-)" ]; }

bootstrap_env() {
  if [ ! -f "$ENV_FILE" ]; then
    cp .env.example "$ENV_FILE"
    log "Created $ENV_FILE from .env.example"
  fi
  ensure_env_value HERMES_DASHBOARD_BASIC_AUTH_PASSWORD gen_secret
  ensure_env_value HERMES_DASHBOARD_BASIC_AUTH_SECRET gen_secret
  ensure_env_value SEARXNG_SECRET gen_secret
}

# ---------------------------------------------------------------- subcommands

case "${1:-}" in
  cp-key)  # ./run-local.sh cp-key <service-account.json>
    [ -f "${2:-}" ] || fail "usage: $0 cp-key <service-account.json>"
    bootstrap_env
    with_env up -d hermes >/dev/null 2>&1 || true
    with_env exec -T hermes mkdir -p /hermes-home/secrets
    with_env cp "$2" hermes:/hermes-home/secrets/hr-drive-sa.json
    log "Service account copied to /hermes-home/secrets/hr-drive-sa.json"
    log "Next: configure rclone remote (see docs/setup.md - Google Drive credentials)"
    exit 0 ;;
esac

# ------------------------------------------------------------- prechecks

command -v docker >/dev/null 2>&1 || fail "Docker CLI not found. Install Docker Desktop first."
docker info >/dev/null 2>&1 || fail "Docker daemon not reachable. Start Docker Desktop and retry."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 required."

# ------------------------------------------------------------ .env bootstrap

bootstrap_env

# ---------------------------------------------------------------- bring-up

log "Building and starting services (first build takes a few minutes)..."
with_env up -d --build

log "Waiting for health checks (timeout ${TIMEOUT_SECS}s)..."
elapsed=0
until [ "$(docker inspect -f '{{.State.Health.Status}}' cps-searxng 2>/dev/null)" = "healthy" ] \
   && [ "$(docker inspect -f '{{.State.Health.Status}}' cps-hermes  2>/dev/null)" = "healthy" ]; do
  if [ "$elapsed" -ge "$TIMEOUT_SECS" ]; then
    warn "Health checks not green yet. Current status:"
    docker compose -f "$COMPOSE_FILE" ps || true
    exit 1
  fi
  sleep 10; elapsed=$((elapsed + 10)); printf '.'
done
echo ""
log "Both services healthy."

# ------------------------------------------------------------ skill sync

if [ -d skill/candidate-sourcing ]; then
  with_env exec -T hermes rm -rf /hermes-home/skills/candidate-sourcing
  with_env cp skill/candidate-sourcing hermes:/hermes-home/skills/candidate-sourcing
  log "Synced skill/candidate-sourcing -> /hermes-home/skills/"
fi

# --------------------------------------------- paused cron job registration

CRON_NAME="candidate-sourcing-daily"

# Fleet-level model pin for ALL cron jobs (this build pins via config keys;
# unpinned jobs resolve to cron.model at fire time - drift guard protects).
if env_nonempty HERMES_CRON_PROVIDER && env_nonempty HERMES_CRON_MODEL; then
  with_env exec -T hermes hermes config set cron.model \
    "$(grep -E '^HERMES_CRON_MODEL=' "$ENV_FILE" | head -1 | cut -d= -f2-)" >/dev/null
  with_env exec -T hermes hermes config set cron.model_provider \
    "$(grep -E '^HERMES_CRON_PROVIDER=' "$ENV_FILE" | head -1 | cut -d= -f2-)" >/dev/null
  # unattended runs must be able to execute the pipeline scripts
  with_env exec -T hermes hermes config set approvals.cron_mode approve >/dev/null
  # global chat default too (dashboard Chat / one-shot runs)
  with_env exec -T hermes hermes config set model \
    "$(grep -E '^HERMES_CRON_MODEL=' "$ENV_FILE" | head -1 | cut -d= -f2-)" >/dev/null
  with_env exec -T hermes hermes config set model_provider \
    "$(grep -E '^HERMES_CRON_PROVIDER=' "$ENV_FILE" | head -1 | cut -d= -f2-)" >/dev/null
  log "Cron model pinned: $(grep -E '^HERMES_CRON_PROVIDER=' "$ENV_FILE" | head -1 | cut -d= -f2-)/$(grep -E '^HERMES_CRON_MODEL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
fi

if [ "$(job_exists "$CRON_NAME")" != "1" ]; then
  DELIVER="local"
  env_nonempty HERMES_DELIVER_TARGET && DELIVER="$(grep -E '^HERMES_DELIVER_TARGET=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  # NOTE: hermes cron create exits 0 even when it fails -> verify via jobs.json.
  with_env exec -T hermes hermes cron create \
        "0 9 * * *" \
        "Run the candidate sourcing workflow end-to-end as specified by the candidate-sourcing skill." \
        --name "$CRON_NAME" --skill candidate-sourcing --deliver "$DELIVER" \
        --workdir /workspace >/dev/null 2>&1 || true
  with_env exec -T hermes hermes cron pause "$CRON_NAME" >/dev/null 2>&1 || true
  if [ "$(job_exists "$CRON_NAME")" = "1" ] && [ "$(job_paused "$CRON_NAME")" = "1" ]; then
    log "Registered cron job '${CRON_NAME}' (paused)."
  else
    warn "Cron registration FAILED - check 'hermes cron create' output inside the container. Re-run later."
  fi
else
  log "Cron job '${CRON_NAME}' already present - leaving untouched."
fi

# ------------------------------------------------------- credential status

MISSING=""
for k in OPENROUTER_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY; do
  env_nonempty "$k" || MISSING="$MISSING $k"
done
LLM_OK=false
if [ -z "$MISSING" ] || [ "$(echo $MISSING | wc -w | tr -d ' ')" -lt 3 ]; then LLM_OK=true; fi

BACKEND="$(grep -E '^backend:' config/workflow.yaml | head -1 | awk '{print $2}')"
GOOGLE_OK=false
if [ "${BACKEND:-local}" != "gdrive" ]; then GOOGLE_OK=true   # local mode: no SA needed
else with_env exec -T hermes test -f /hermes-home/secrets/hr-drive-sa.json 2>/dev/null && GOOGLE_OK=true; fi

echo ""
DASH_USER="$(grep -E '^HERMES_DASHBOARD_BASIC_AUTH_USERNAME=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
log "Dashboard:      http://localhost:9119  (user: ${DASH_USER:-admin})"
if $LLM_OK; then log "LLM key:        OK"
else warn "LLM key:        MISSING -> set one of:${MISSING} in .env (then re-run)"; fi
if $GOOGLE_OK && [ "${BACKEND:-local}" != "gdrive" ]; then
  log "Storage:        local queue folders (no external creds needed)"
elif $GOOGLE_OK; then
  log "Google SA:      OK (/hermes-home/secrets/hr-drive-sa.json)"
else
  warn "Google SA:      MISSING -> './run-local.sh cp-key <file>' (see docs/setup.md)"
fi

if $LLM_OK && $GOOGLE_OK; then
  log "All credentials present. Resume the cron job when ready:"
  log "  docker compose -f deploy/docker-compose.yml exec hermes hermes cron resume $CRON_NAME"
else
  warn "Cron job stays PAUSED until credentials above are provided."
fi
