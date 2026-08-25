"""Tests for drive_sync.py - backends, queue semantics, failure counters.

Covers tasks 3.1 (local backend round-trip, no network), 3.2 (backend
selection + clean switching + unknown fails fast), 3.3 (three-strike
quarantine), 3.4 (inbox detection). rclone is stubbed via runner injection.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

drive_sync = importlib.import_module("drive_sync")

CFG_BASE = {
    "storage": {"backend": "local"},
    "drive": {
        "remote": "hr-drive",
        "folders": {
            "jds_pending": "jds-pending",
            "jds_processed": "jds-processed",
            "jds_failed": "jds-failed",
            "exports_inbox": "exports-inbox",
        },
        "quarantine_after_consecutive_failures": 3,
    },
}


class FakeRclone:
    """In-memory Drive: folder -> {name: content}."""

    def __init__(self, tree):
        self.tree = tree
        self.moves = []

    def __call__(self, args):
        class P:
            def __init__(self, rc=0, out="", err=""):
                self.returncode, self.stdout, self.stderr = rc, out, err

        if args[0] == "lsjson":
            folder = args[1].split(":", 1)[1]
            entries = [{"Name": n, "IsDir": False}
                       for n, c in sorted(self.tree.get(folder, {}).items())]
            return P(0, json.dumps(entries))
        if args[0] == "cat":
            _, path = args[1].split(":", 1)
            folder, name = path.split("/", 1)
            try:
                return P(0, self.tree[folder][name])
            except KeyError:
                return P(3, "", f"error: {path} not found")
        if args[0] == "moveto":
            src, dst = args[1].split(":", 1)[1], args[2].split(":", 1)[1]
            sf, sn = src.split("/", 1)
            df, dn = dst.split("/", 1)
            self.tree.setdefault(df, {})
            if sn not in self.tree[sf]:
                return P(0, "")                      # already gone -> success
            self.moves.append((sf, sn, df))
            self.tree[df][dn] = self.tree[sf].pop(sn)
            return P(0, "")
        raise AssertionError(f"unexpected rclone call: {args}")


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(drive_sync, "load_config", lambda: CFG_BASE)
    state_dir = Path("/tmp") / "cps-state-test"
    monkeypatch.setattr(drive_sync, "state_dir", lambda: state_dir)
    return CFG_BASE


# --------------------------------------------------- task 3.2: selection

def test_unknown_backend_fails_fast_named():
    with pytest.raises(drive_sync.BackendError) as exc:
        drive_sync.resolve_backend_name({"storage": {"backend": "s3"}})
    assert "s3" in str(exc.value) and "local" in str(exc.value) and "gdrive" in str(exc.value)


def test_backend_defaults_to_local_when_unspecified():
    assert drive_sync.resolve_backend_name({}) == "local"


def test_switching_backends_cleanly(cfg):   # spec: switch must not change semantics
    local = drive_sync.get_backend(CFG_BASE)
    gdrive_cfg = json.loads(json.dumps(CFG_BASE | {"storage": {"backend": "gdrive"}}))
    gdrive = drive_sync.get_backend(gdrive_cfg)
    assert isinstance(local, drive_sync.LocalBackend)
    assert isinstance(gdrive, drive_sync.GdriveBackend)


# --------------------------------------------------- task 3.1: local backend

def test_local_round_trip_no_network(tmp_path):
    roots = {k: tmp_path / k.replace("_", "-") for k in drive_sync.FOLDER_KEYS}
    be = drive_sync.LocalBackend(roots=roots)
    (roots["jds_pending"] / "jd-a.md").write_text("# role A", encoding="utf-8")
    (roots["exports_inbox"] / "export.csv").write_text("name\nA\n", encoding="utf-8")

    assert be.list_names("jds_pending") == ["jd-a.md"]
    assert be.read_file("jds_pending", "jd-a.md") == "# role A"
    assert be.list_names("exports_inbox") == ["export.csv"]

    be.move("jds_pending", "jd-a.md", "jds_processed")
    assert be.list_names("jds_pending") == []
    assert be.list_names("jds_processed") == ["jd-a.md"]


def test_local_move_idempotent_when_already_gone(tmp_path):
    roots = {k: tmp_path / k for k in drive_sync.FOLDER_KEYS}
    be = drive_sync.LocalBackend(roots=roots)
    be.move("jds_pending", "ghost.md", "jds_processed")     # must not raise
    be.move("jds_pending", "ghost.md", "jds_processed")


def test_local_defaults_anchor_to_repo_root(tmp_path, monkeypatch):
    from config_loader import repo_root
    be = drive_sync.LocalBackend()
    assert be.roots["jds_pending"] == repo_root() / "data" / "jds-pending"


def test_local_env_overrides_take_precedence(tmp_path, monkeypatch):
    custom = tmp_path / "custom-pending"
    monkeypatch.setenv("CPS_JDS_PENDING_DIR", str(custom))
    be = drive_sync.LocalBackend()
    assert be.roots["jds_pending"] == custom and custom.is_dir()


def test_pipeline_api_uses_injected_backend(tmp_path):
    roots = {k: tmp_path / k for k in drive_sync.FOLDER_KEYS}
    be = drive_sync.LocalBackend(roots=roots)
    (roots["jds_pending"] / "x.md").write_text("x", encoding="utf-8")

    assert drive_sync.list_pending(get=lambda: be) == ["x.md"]
    assert drive_sync.read_jd("x.md", get=lambda: be) == "x"
    drive_sync.mark_processed("x.md", get=lambda: be)
    assert drive_sync.list_pending(get=lambda: be) == []


# -------------------------------------------------- gdrive backend (dormant)

def test_gdrive_backend_list_read_move_via_runner(cfg):
    fake = FakeRclone({
        "jds-pending": {"jd-a.md": "# role A"},
        "exports-inbox": {"export.csv": "name\nA\n"},
    })
    be = drive_sync.GdriveBackend(runner=fake, cfg=cfg)

    assert be.list_names("jds_pending") == ["jd-a.md"]
    assert be.read_file("jds_pending", "jd-a.md") == "# role A"
    assert be.list_names("exports_inbox") == ["export.csv"]
    be.move("jds_pending", "jd-a.md", "jds_processed")
    assert ("jds-pending", "jd-a.md", "jds-processed") in fake.moves


def test_gdrive_move_after_success_semantics_idempotent(cfg):
    fake = FakeRclone({"jds-pending": {"jd-a.md": "# A"}})
    be = drive_sync.GdriveBackend(runner=fake, cfg=cfg)
    be.move("jds_pending", "jd-a.md", "jds_processed")
    be.move("jds_pending", "jd-a.md", "jds_processed")       # second: no raise
    assert len(fake.moves) == 1


# --------------------------------------------------- task 3.3: counters

def test_failure_counter_three_strikes_quarantines(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(drive_sync, "state_dir", lambda: tmp_path / "state")
    roots = {k: tmp_path / k for k in drive_sync.FOLDER_KEYS}
    be = drive_sync.LocalBackend(roots=roots)
    (roots["jds_pending"] / "bad.md").write_text("bad", encoding="utf-8")

    drive_sync.record_failure("bad.md")
    assert not drive_sync.should_quarantine("bad.md")
    drive_sync.record_failure("bad.md")
    assert not drive_sync.should_quarantine("bad.md")

    # strike three -> quarantine + reset
    drive_sync.quarantine("bad.md", get=lambda: be)
    drive_sync.reset_failures("bad.md")
    assert be.list_names("jds_failed") == ["bad.md"]
    assert not drive_sync.should_quarantine("bad.md")


# --------------------------------------------------- task 3.4: inbox detection

def test_inbox_listing_local(tmp_path):
    roots = {k: tmp_path / k for k in drive_sync.FOLDER_KEYS}
    be = drive_sync.LocalBackend(roots=roots)
    (roots["exports_inbox"] / "a.csv").write_text("name\nA\n", encoding="utf-8")
    (roots["exports_inbox"] / "b.csv").write_text("name\nB\n", encoding="utf-8")
    (roots["exports_inbox"] / "subdir").mkdir()               # dirs ignored
    assert drive_sync.list_inbox(get=lambda: be) == ["a.csv", "b.csv"]
