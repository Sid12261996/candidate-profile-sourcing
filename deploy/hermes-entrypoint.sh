#!/bin/sh
# Entrypoint for the hermes runtime container.
# Runs the messaging/cron gateway in the background and the web dashboard in
# the foreground. The dashboard binds 0.0.0.0, so basic-auth env vars are
# required (compose supplies them from .env) or Hermes fails closed at startup.
set -eu

HERMES_HOME="${HERMES_HOME:-/hermes-home}"
export HERMES_HOME

mkdir -p "${HERMES_HOME}/skills" "${HERMES_HOME}/secrets"

# First boot on a fresh volume: seed bundled skill so the runtime is never empty.
if [ ! -d "${HERMES_HOME}/skills/candidate-sourcing" ] && [ -d /opt/skill/candidate-sourcing ]; then
  cp -r /opt/skill/candidate-sourcing "${HERMES_HOME}/skills/candidate-sourcing"
fi

echo "[entrypoint] starting gateway..."
hermes gateway &
GATEWAY_PID=$!

shutdown() {
  echo "[entrypoint] shutting down..."
  kill "$GATEWAY_PID" 2>/dev/null || true
  exit 0
}
trap shutdown INT TERM

echo "[entrypoint] starting dashboard on 0.0.0.0:9119..."
exec hermes dashboard --host 0.0.0.0 --port 9119 --no-open
