"""Queue storage operations for the candidate-sourcing skill (design D3).

One internal contract - list/read/move over semantic folder keys - with two
backends selected by workflow.yaml (`storage.backend`):

  local  (default) plain folders under data/, paths from CPS_* env vars,
                   zero network, zero external credentials
  gdrive           same folders via rclone (production switch; dormant)

Queue semantics are backend-invariant and spec'd once in jd-intake:
move-after-success, quarantine after N consecutive failures.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from config_loader import folders as cfg_folders, load_config, remote as cfg_remote, state_dir

Runner = Callable[[list[str]], "subprocess.CompletedProcess"]

FOLDER_KEYS = ("jds_pending", "jds_processed", "jds_failed", "exports_inbox")

LOCAL_ENV_DEFAULTS = {
    "jds_pending": ("CPS_JDS_PENDING_DIR", "data/jds-pending"),
    "jds_processed": ("CPS_JDS_PROCESSED_DIR", "data/jds-processed"),
    "jds_failed": ("CPS_JDS_FAILED_DIR", "data/jds-failed"),
    "exports_inbox": ("CPS_EXPORTS_INBOX_DIR", "data/exports-inbox"),
}

VALID_BACKENDS = ("local", "gdrive")


class BackendError(ValueError):
    """Unknown storage backend name -> fail fast at startup."""


def resolve_backend_name(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    name = (cfg.get("storage") or {}).get("backend", "local")
    if name not in VALID_BACKENDS:
        raise BackendError(
            f"unknown storage backend {name!r} (valid: {', '.join(VALID_BACKENDS)})"
        )
    return name


def run_rclone(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["rclone", *args], capture_output=True, text=True, timeout=120)


# ------------------------------------------------------------------ backends

class LocalBackend:
    """Plain-folder queue. Roots resolved from env vars with data/ defaults."""

    def __init__(self, roots: dict[str, str | Path] | None = None):
        self.roots: dict[str, Path] = {}
        for key in FOLDER_KEYS:
            if roots and key in roots:
                self.roots[key] = Path(roots[key])
            else:
                env_name, default = LOCAL_ENV_DEFAULTS[key]
                base = os.environ.get(env_name, default)
                # relative paths anchor to the repo root so cwd never matters
                path = Path(base)
                if not path.is_absolute():
                    path = _repo_root() / path
                self.roots[key] = path
        for path in self.roots.values():
            path.mkdir(parents=True, exist_ok=True)

    def list_names(self, key: str) -> list[str]:
        # skip dotfiles (.gitkeep etc.) - only real documents are queue items
        return sorted(p.name for p in self.roots[key].iterdir()
                      if p.is_file() and not p.name.startswith("."))

    def read_file(self, key: str, name: str) -> str:
        return (self.roots[key] / name).read_text(encoding="utf-8")

    def move(self, src_key: str, name: str, dst_key: str) -> None:
        src, dst = self.roots[src_key] / name, self.roots[dst_key] / name
        if not src.exists():
            return                      # already moved -> idempotent success
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


class GdriveBackend:
    """rclone-backed queue (identical semantics). Runner injectable for tests."""

    def __init__(self, runner: Runner = run_rclone, cfg: dict | None = None):
        self.runner = runner
        self.cfg = cfg or load_config()
        self.folders = cfg_folders(self.cfg)
        self.remote = cfg_remote(self.cfg)

    def _check(self, proc: subprocess.CompletedProcess, context: str):
        if proc.returncode != 0:
            raise RuntimeError(f"rclone {context} failed: {proc.stderr.strip()}")

    def list_names(self, key: str) -> list[str]:
        proc = self.runner(["lsjson", f"{self.remote}:{self.folders[key]}"])
        self._check(proc, f"lsjson {key}")
        entries = json.loads(proc.stdout or "[]")
        return sorted(e["Name"] for e in entries
                      if not e.get("IsDir", False)
                      and not e.get("Name", "").startswith("."))

    def read_file(self, key: str, name: str) -> str:
        proc = self.runner(["cat", f"{self.remote}:{self.folders[key]}/{name}"])
        self._check(proc, f"cat {key}/{name}")
        return proc.stdout

    def move(self, src_key: str, name: str, dst_key: str) -> None:
        proc = self.runner([
            "moveto",
            f"{self.remote}:{self.folders[src_key]}/{name}",
            f"{self.remote}:{self.folders[dst_key]}/{name}",
        ])
        if proc.returncode != 0 and "directory not found" not in proc.stderr.lower():
            raise RuntimeError(
                f"rclone moveto {src_key}/{name} -> {dst_key}/ failed: {proc.stderr.strip()}"
            )


def get_backend(cfg: dict | None = None):
    name = resolve_backend_name(cfg)
    if name == "gdrive":
        return GdriveBackend(cfg=cfg)
    return LocalBackend()


def _repo_root() -> Path:
    from config_loader import repo_root
    return repo_root()


# --------------------------------------------------- backend-facing pipeline API

def list_pending(get=get_backend) -> list[str]:
    return get().list_names("jds_pending")


def list_inbox(get=get_backend) -> list[str]:
    return get().list_names("exports_inbox")


def read_jd(name: str, get=get_backend) -> str:
    return get().read_file("jds_pending", name)


def mark_processed(name: str, get=get_backend) -> None:
    get().move("jds_pending", name, "jds_processed")


def quarantine(name: str, src_key: str = "jds_pending", get=get_backend) -> None:
    get().move(src_key, name, "jds_failed")


# ------------------------------------------------- failure counters (task 3.3)

def state_file() -> Path:
    return state_dir() / "jd-failures.json"


def _load_state() -> dict:
    try:
        return json.loads(state_file().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def record_failure(name: str) -> int:
    state = _load_state()
    count = int(state.get(name, 0)) + 1
    state[name] = count
    _save_state(state)
    return count


def reset_failures(name: str) -> None:
    state = _load_state()
    state.pop(name, None)
    _save_state(state)


def should_quarantine(name: str) -> bool:
    threshold = int(load_config()["drive"]["quarantine_after_consecutive_failures"])
    return int(_load_state().get(name, 0)) >= threshold


# ------------------------------------------------------------ CLI for testing

def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI wrapper
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "list-pending":
        print("\n".join(list_pending()))
    elif cmd == "list-inbox":
        print("\n".join(list_inbox()))
    elif cmd == "read":
        print(read_jd(sys.argv[2]))
    elif cmd == "move":
        mark_processed(sys.argv[2])
    elif cmd == "quarantine":
        record_failure(sys.argv[2])
        if should_quarantine(sys.argv[2]):
            quarantine(sys.argv[2])
            reset_failures(sys.argv[2])
            print("quarantined")
        else:
            print(f"failure recorded ({_load_state().get(sys.argv[2], '?')})")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
