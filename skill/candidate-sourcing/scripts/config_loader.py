"""Shared configuration loading for candidate-sourcing skill scripts.

Resolution order for the workflow config:
  1. $CPS_CONFIG env var
  2. /workspace/config/workflow.yaml   (container: repo bind-mount)
  3. <script>/../../../config/workflow.yaml (host checkout)

State directory (persistent across runs):
  1. $CPS_STATE_DIR
  2. $HERMES_HOME/state                (container volume)
  3. .hermes-local/                    (gitignored host fallback)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent


def repo_root() -> Path:
    return _SCRIPT_DIR.parents[2]


def config_path() -> Path:
    if os.environ.get("CPS_CONFIG"):
        return Path(os.environ["CPS_CONFIG"])
    container = Path("/workspace/config/workflow.yaml")
    if container.exists():
        return container
    return repo_root() / "config" / "workflow.yaml"


def load_config() -> dict:
    with open(config_path(), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def state_dir() -> Path:
    if os.environ.get("CPS_STATE_DIR"):
        return Path(os.environ["CPS_STATE_DIR"])
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]) / "state"
    return repo_root() / ".hermes-local"


def folders(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    return cfg["drive"]["folders"]


def remote(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    return cfg["drive"]["remote"]
