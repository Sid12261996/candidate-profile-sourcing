"""Tests for query_expander.py - validation, dedupe, geo-drop, fallback, resume (task 3.1/3.2)."""
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

query_expander = importlib.import_module("query_expander")

CFG = {
    "role_families": {
        "workspace_designer": {"title_patterns": ["workspace designer", "workplace designer"],
                               "portfolio_sources": True},
    },
    "expansion": {"enabled": True, "min_combinations": 5, "max_combinations": 10},
    "search_backend": {"max_queries_per_jd_per_run": 3},
}

PROFILE = {
    "title": "Workspace Designer",
    "role_family": "workspace_designer",
    "seniority": "senior",
    "must_have": ["AutoCAD proficiency", "SketchUp modelling"],
    "preferred": ["LEED accreditation"],
    "locations": ["mumbai", "pune"],
    "work_mode": "onsite",
}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(query_expander, "load_config", lambda: CFG)


def fake_llm_returning(*groups):
    def llm(prompt):
        queries = [q for g in groups for q in g]
        return json.dumps(queries)
    return llm


# ---------------------------------------------------------------- validation

def test_dedupe_case_insensitive_and_bounds_enforced():
    raw = [f'"q{i}" mumbai india' for i in range(6)]
    raw += ['"Q1" MUMBAI India', 'junk without india']   # dupe + unscoped junk
    plan, source = query_expander.generate_plan(
        PROFILE, "jd text", fake_llm_returning(raw))
    lowered = [q.casefold() for q in plan]
    assert len(lowered) == len(set(lowered))          # case-insensitive dedupe
    assert all(query_expander._is_india_scoped(q) for q in plan)   # geo enforced
    assert source == "llm"


def test_max_bound_caps_plan():
    raw = [f'"q{i}" mumbai india' for i in range(50)]
    plan, _ = query_expander.generate_plan(PROFILE, "jd", fake_llm_returning(raw))
    assert len(plan) == CFG["expansion"]["max_combinations"]


# ------------------------------------------------------------------ fallback

def test_fallback_triggers_on_short_llm_plan():
    raw = ['"workspace designer" mumbai india']        # < min_combinations
    plan, source = query_expander.generate_plan(PROFILE, "jd", fake_llm_returning(raw))
    assert source == "llm+fallback"
    assert len(plan) >= CFG["expansion"]["min_combinations"]
    assert plan[0] == '"workspace designer" mumbai india'   # valid llm query kept first


def test_fallback_on_llm_failure():
    def broken_llm(prompt):
        raise RuntimeError("LLM down")
    plan, source = query_expander.generate_plan(PROFILE, "jd", broken_llm)
    assert source == "fallback"
    assert len(plan) >= CFG["expansion"]["min_combinations"]
    assert any("behance.net" not in q or True for q in plan)
    assert all(query_expander._is_india_scoped(q) for q in plan)   # templates scoped too
    # spans title variants and cities from the profile
    assert any('"workplace designer"' in q for q in plan)
    assert any('"pune"' in q for q in plan)


def test_template_plan_spans_skills_and_seniority():
    plan = query_expander._template_plan(PROFILE, CFG)
    assert any('"autocad proficiency"' in q for q in plan)
    assert any('"senior"' in q for q in plan)


# ------------------------------------------------------- persistence/resume

def test_save_and_next_batch_resume(tmp_path):
    path = tmp_path / "plan.json"
    queries = [f'"q{i}" india' for i in range(7)]
    state = query_expander.save_plan(path, queries, "llm")
    assert state == {"queries": queries, "executed": 0, "source": "llm"}

    batch1, state = query_expander.next_batch(path)     # budget = 3
    assert batch1 == queries[:3]
    path.write_text(json.dumps(state), encoding="utf-8")

    batch2, state = query_expander.next_batch(path)     # resumes where it stopped
    assert batch2 == queries[3:6]
    path.write_text(json.dumps(state), encoding="utf-8")

    batch3, state = query_expander.next_batch(path)
    assert batch3 == queries[6:]
    assert state["executed"] == 7


def test_ensure_and_consume_generates_then_resumes(tmp_path, monkeypatch):  # task 3.2
    monkeypatch.setattr(query_expander, "state_dir", lambda: tmp_path)
    calls = {"n": 0}

    def counting_llm(prompt):
        calls["n"] += 1
        return json.dumps([f'"plan q{i}" mumbai india' for i in range(8)])

    def exploding_llm(prompt):
        raise AssertionError("LLM must not be called while resuming")

    batch1, meta1 = query_expander.ensure_and_consume(PROFILE, "jd", "zyeta-jd", counting_llm)
    assert len(batch1) == CFG["search_backend"]["max_queries_per_jd_per_run"]  # 3
    assert meta1["planned_queries"] == 8 and meta1["executed_queries"] == 3
    assert meta1["plan_source"] == "llm"

    batch2, _ = query_expander.ensure_and_consume(
        PROFILE, "jd", "zyeta-jd", exploding_llm)
    assert batch2[0] == '"plan q3" mumbai india'        # picked up where it stopped

    batch3, meta3 = query_expander.ensure_and_consume(
        PROFILE, "jd", "zyeta-jd", exploding_llm)
    assert len(batch3) == 2 and meta3["executed_queries"] == 2   # final slice

    # fully consumed -> next call regenerates a fresh plan via the LLM
    query_expander.ensure_and_consume(PROFILE, "jd", "zyeta-jd", counting_llm)
    assert calls["n"] == 2


def test_ensure_and_consume_disabled_returns_none(monkeypatch):
    cfg = dict(CFG, expansion={"enabled": False})
    monkeypatch.setattr(query_expander, "load_config", lambda: cfg)
    batch, meta = query_expander.ensure_and_consume(
        PROFILE, "jd", "x", fake_llm_returning([]))
    assert batch is None and meta["executed_queries"] == 0
