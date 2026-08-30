"""End-to-end pipeline test with stubbed LLM + local fixtures (task 5.2/6.1).

No network: Track A/portfolio backends fail fast (unreachable SearXNG, no
duckduckgo fallback) and candidates enter via a Track B export instead.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

pipeline = importlib.import_module("pipeline")
drive_sync = importlib.import_module("drive_sync")
exclusions = importlib.import_module("exclusions")
ledger = importlib.import_module("ledger")

JD_TEXT = "# Workspace Designer\nWe need a designer for our studio.\n"

CSV_EXPORT = """First Name,Last Name,Current Title,Current Company,Location,Profile URL
Zerod,Nil,Designer,ZCorp,Mumbai,u://zerod
Hina,High,Sr Designer,HCo,Mumbai,u://high
"""

CFG = {
    "storage": {"backend": "local"},
    "role_families": {},
    "defaults": {"work_mode": "onsite"},
    "hard_filters": {},
    "scoring": {"top_n_per_jd_per_run": 10,
                "exclude_zero_scores": True,
                "max_scored_per_jd_per_run": 150},
    "expansion": {"enabled": False},
    "search_backend": {"max_queries_per_jd_per_run": 4},
}


class FakeBackend:
    def __init__(self, roots):
        self.roots = {k: Path(v) for k, v in roots.items()}
        for p in self.roots.values():
            p.mkdir(parents=True, exist_ok=True)

    def list_names(self, key):
        return sorted(p.name for p in self.roots[key].iterdir()
                      if p.is_file() and not p.name.startswith("."))

    def read_file(self, key, name):
        return (self.roots[key] / name).read_text(encoding="utf-8")

    def move(self, src_key, name, dst_key):
        src, dst = self.roots[src_key] / name, self.roots[dst_key] / name
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)


@pytest.fixture
def env(tmp_path, monkeypatch):
    roots = {
        "jds_pending": tmp_path / "pending", "jds_processed": tmp_path / "processed",
        "jds_failed": tmp_path / "failed", "exports_inbox": tmp_path / "inbox",
    }
    for p in roots.values():
        p.mkdir(parents=True, exist_ok=True)
    (roots["jds_pending"] / "test-jd.md").write_text(JD_TEXT)
    (roots["exports_inbox"] / "export.csv").write_text(CSV_EXPORT)

    backend = FakeBackend(roots)
    monkeypatch.setattr(drive_sync, "get_backend", lambda cfg=None: backend)
    monkeypatch.setattr(drive_sync, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(exclusions, "state_dir", lambda: tmp_path / "state")
    import scoring as scoring_mod
    monkeypatch.setattr(scoring_mod, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setenv("CPS_LEDGER_PATH", str(tmp_path / "candidates.xlsx"))
    monkeypatch.setattr(pipeline, "load_config", lambda: CFG)

    def stub_llm_factory(*a, **k):
        def llm(prompt):
            if "Zerod" in prompt:
                return '{"score": 0, "justification": "established non-India base"}'
            return '{"score": 82, "justification": "strong match"}'
        return llm
    import openrouter_llm
    monkeypatch.setattr(openrouter_llm, "make_llm_fn", stub_llm_factory)
    return {"tmp": tmp_path, "backend": backend}


def test_zero_scores_never_reach_ledger(env):            # task 5.2
    summary = pipeline.run()
    assert summary["status"] == "ok"
    jd_summary = summary["jds"][0]
    assert jd_summary["added"] == 1                      # only the scorer > 0

    ledger_path = env["tmp"] / "candidates.xlsx"
    rows = ledger.load_rows(ledger_path)
    assert [r["candidate_name"] for r in rows] == ["Hina High"]
    assert int(rows[0]["score"]) == 82

    # zero-score candidate registered in the workflow-owned registry...
    reg = env["tmp"] / "state" / "exclusions.json"
    assert "u://zerod" in exclusions.urls(reg)
    # ...and the human Excel ledger is untouched by those exclusions
    assert len(rows) == 1


def test_registered_zero_score_skipped_on_next_run(env, monkeypatch):  # task 5.1 e2e half
    pipeline.run()
    # fresh export re-surfaces the zero-scored candidate under a new URL row
    env["backend"].roots["exports_inbox"].joinpath("export2.csv").write_text(CSV_EXPORT)

    calls = {"n": 0}

    def counting_factory(*a, **k):
        def llm(prompt):
            calls["n"] += 1
            return '{"score": 70, "justification": "ok"}'
        return llm
    import openrouter_llm
    monkeypatch.setattr(openrouter_llm, "make_llm_fn", counting_factory)

    # rerun with a NEW pending JD so the queue is not silent
    (env["backend"].roots["jds_pending"] / "test-jd.md").write_text(JD_TEXT)
    summary = pipeline.run()
    assert summary["jds"][0].get("exclusion_skipped") == 1
    # Zerod consumed NO rubric token this run (skipped pre-scoring)
    assert calls["n"] == 1                # only Hina was scored again
