# Hermes runtime image for the candidate sourcing stack.
# Pinned versions - bump deliberately, one PR at a time.
FROM python:3.13-slim

ARG HERMES_VERSION=0.19.0
ARG RCLONE_VERSION=v1.75.0
ARG OPENPYXL_VERSION=3.1.5

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HERMES_HOME=/hermes-home

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip tini \
 && rm -rf /var/lib/apt/lists/*

# rclone: Drive list/read/move for the JD queue (D3)
RUN curl -fsSL -o /tmp/rclone.zip \
      "https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-linux-amd64.zip" \
 && unzip -j /tmp/rclone.zip "*/rclone" -d /usr/local/bin \
 && chmod +x /usr/local/bin/rclone \
 && rm /tmp/rclone.zip \
 && rclone version | head -1

# Hermes agent with the extras this stack needs:
#   web  -> dashboard (FastAPI/uvicorn)
#   pty  -> embedded chat terminal
#   cron -> scheduler inside the gateway
#   mcp  -> MCP client
RUN pip install "hermes-agent[web,pty,cron,mcp]==${HERMES_VERSION}" \
 && pip install "openpyxl==${OPENPYXL_VERSION}" \
 && pip install "anthropic" \
 && hermes --version || true

# Skill payload is synced into the volume by run-local.sh; baked copy is a fallback.
COPY skill/ /opt/skill/
COPY deploy/hermes-entrypoint.sh /usr/local/bin/hermes-entrypoint
RUN chmod +x /usr/local/bin/hermes-entrypoint

VOLUME ["/hermes-home"]
EXPOSE 9119

ENTRYPOINT ["/usr/bin/tini", "--", "hermes-entrypoint"]
