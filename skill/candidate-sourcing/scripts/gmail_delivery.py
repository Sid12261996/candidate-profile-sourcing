"""Send the candidates ledger to Gmail after a productive run."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

DELIVERY_MARKER_FILE = ".delivery_cache.json"


def send_ledger_email(ledger_path: Path, recipient: str) -> None:
    """Email the candidates.xlsx ledger file to the configured recipient via Hermes gateway.

    This function requires the Hermes runtime to have Gmail credentials already provisioned
    via OAuth. On first call, the runtime will handle the browser redirect for auth.

    Args:
        ledger_path: Path to the candidates.xlsx file
        recipient: Email address to send to (typically from config)

    Raises:
        Exception: On Gmail API failure (not caught; caller decides fail-soft behavior)
    """
    if not ledger_path.exists():
        raise FileNotFoundError(f"Ledger file not found: {ledger_path}")

    file_size_mb = ledger_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 20:
        raise ValueError(f"Ledger file too large ({file_size_mb:.1f} MB); Gmail limit ~20 MB")

    ledger_hash = _ledger_hash(ledger_path)
    marker = _read_delivery_marker()

    if marker and marker.get("ledger_hash") == ledger_hash:
        return  # Already delivered this exact ledger; skip duplicate send

    try:
        _do_send_via_hermes_api(ledger_path, recipient)
        _write_delivery_marker({"ledger_hash": ledger_hash})
    except Exception:
        raise  # Caller handles fail-soft


def _ledger_hash(ledger_path: Path) -> str:
    """SHA-256 of ledger file for idempotency check."""
    with open(ledger_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _read_delivery_marker() -> dict | None:
    """Read the last successful delivery marker."""
    # Use data directory (which is writable) instead of workspace root
    marker_path = Path(os.environ.get("CPS_EXPORTS_INBOX_DIR", "data/exports-inbox")).parent / DELIVERY_MARKER_FILE
    if not marker_path.exists():
        return None
    try:
        with open(marker_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _write_delivery_marker(data: dict) -> None:
    """Write a delivery marker to guard against re-sends."""
    # Use data directory (which is writable) instead of workspace root
    marker_path = Path(os.environ.get("CPS_EXPORTS_INBOX_DIR", "data/exports-inbox")).parent / DELIVERY_MARKER_FILE
    with open(marker_path, "w") as f:
        json.dump(data, f)


def _do_send_via_hermes_api(ledger_path: Path, recipient: str) -> None:
    """Send email via Hermes gateway API.

    The Hermes agent runtime exposes a local API (typically http://localhost:9119) with
    message/tool endpoints. This function makes a request to it to send mail via the
    agent's Gmail integration.

    If HERMES_GATEWAY_URL is not set, tries localhost:9119 (compose default).
    """
    import base64
    import urllib.request
    import urllib.error

    gateway_url = os.environ.get("HERMES_GATEWAY_URL", "http://localhost:9119")

    with open(ledger_path, "rb") as f:
        file_bytes = f.read()

    file_b64 = base64.b64encode(file_bytes).decode("ascii")

    payload = {
        "subject": "Candidate Sourcing Ledger",
        "to": recipient,
        "body": "Latest candidate shortlist from daily sourcing run.",
        "file_b64": file_b64,
        "file_name": "candidates.xlsx"
    }

    try:
        req = urllib.request.Request(
            f"{gateway_url}/send-email",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Hermes API returned {response.status}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach Hermes gateway at {gateway_url}: {e}")
