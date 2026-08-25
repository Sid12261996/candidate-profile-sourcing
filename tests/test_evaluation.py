"""Tests for evaluation stage: filters, scoring, top-N, dedup (tasks 7.1-7.4)."""
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

score_filters = importlib.import_module("score_filters")
scoring = importlib.import_module("scoring")
topn = importlib.import_module("topn")
dedup = importlib.import_module("dedup")

PROFILE = {
    "title": "Workspace Designer",
    "experience_band_years": {"min": 6, "max": None},
    "locations": ["mumbai"],
}


def rec(**kw):
    base = {"name": "X", "profile_url": None, "source_urls": []}
    return {**base, **kw}


# ---------------------------------------------------------------- filters 7.1

def test_filter_eliminates_location_mismatch():
    survivors, eliminated = score_filters.apply_hard_filters(
        [rec(name="A", location="Delhi")], PROFILE)
    assert survivors == []
    assert eliminated[0]["eliminated_because"].startswith("location")


def test_filter_passes_matching_location():
    survivors, _ = score_filters.apply_hard_filters(
        [rec(name="B", location="Mumbai, MH", experience_years=8)], PROFILE)
    assert survivors and survivors[0]["unverified"] == []


def test_missing_data_passes_flagged_never_rejected():
    survivors, eliminated = score_filters.apply_hard_filters(
        [rec(name="C", location=None, experience_years=None)], PROFILE)
    assert not eliminated
    assert sorted(survivors[0]["unverified"]) == ["experience", "location"]


def test_filter_ignores_unspecified_profile_constraints():
    profile = dict(PROFILE, locations=[], experience_band_years={"min": None})
    survivors, eliminated = score_filters.apply_hard_filters(
        [rec(name="D", location=None, experience_years=1)], profile)
    assert len(survivors) == 1 and eliminated == []


# ---------------------------------------------------------------- scoring 7.2

def test_score_candidate_parses_and_clamps():
    def llm(prompt):
        assert "Workspace Designer" in prompt and '"name": "E"' in prompt
        return 'Sure!\n```json\n{"score": 143, "justification": "strong"}\n```'
    out = scoring.score_candidate(PROFILE, rec(name="E", location="Mumbai"), llm)
    assert out == {"score": 100, "justification": "strong",
                   "profile_url": None}


def test_save_scores_persists_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, "state_dir", lambda: tmp_path)
    path = scoring.save_scores("Lead Designer / Q3", [{"score": 90}])
    assert json.loads(path.read_text()) == [{"score": 90}]
    assert "Lead_Designer_Q3" in path.name


# ------------------------------------------------------------------ topN 7.3

SCORED = [rec(name=f"C{i}", score=s, source_urls=[f"u://i{i}"])
          for i, s in enumerate([88, 91, 95, 70, 84, 99, 61, 77, 93, 55,
                                 81, 66, 72, 58, 90])]


def test_top_n_returns_ten_when_more_qualify():
    picked = topn.select_top_n(SCORED, n=10)
    assert len(picked) == 10 and max(p["score"] for p in picked) == 99


def test_top_n_returns_all_when_fewer_qualify():
    few = SCORED[:4]
    picked = topn.select_top_n(few, n=10)
    assert len(picked) == 4


def test_top_n_excluded_urls_never_occupy_slots():
    excluded = {"u://i5"}                       # the 99-scorer is already in ledger
    picked = topn.select_top_n(SCORED, excluded_urls=excluded, n=10)
    assert all("u://i5" not in p["source_urls"] for p in picked)


def test_top_n_zero_survivors():
    assert topn.select_top_n([], n=10) == []


def test_top_n_ties_break_deterministically():
    tied = [rec(name="Zoe", score=80, source_urls=["a"]),
            rec(name="Amy", score=80, source_urls=["b"])]
    assert topn.select_top_n(tied, n=1)[0]["name"] == "Amy"


# ------------------------------------------------------------------ dedup 7.4

CFG_DEDUP = {"dedup": {"fuzzy_name_employer": {"enabled": True, "threshold": 0.85}}}
LEDGER = [{"candidate_name": "Priya Sharma", "company": "StudioX",
           "profile_url": "https://in.linkedin.com/in/priya"}]


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(dedup, "load_config", lambda: CFG_DEDUP)


def test_exact_url_match_is_confident_duplicate():   # spec scenario: re-found via other track
    status, matched = dedup.classify(
        rec(name="P. Sharma", company="Different Co",
            source_urls=["https://in.linkedin.com/in/priya"]), LEDGER)
    assert (status, matched) == ("duplicate", LEDGER[0])


def test_uncertain_match_flagged_not_hidden():       # spec scenario: possible-duplicate
    status, matched = dedup.classify(
        rec(name="Priya Sharma", company="StudioX",
            source_urls=["https://in.linkedin.com/in/different-person"]), LEDGER)
    assert status == "possible-duplicate" and matched == LEDGER[0]


def test_clearly_new_person_is_new():
    status, _ = dedup.classify(
        rec(name="Arjun Mehta", company="NovaWorks",
            source_urls=["https://in.linkedin.com/in/arjun-mehta"]), LEDGER)
    assert status == "new"


def test_apply_dedup_annotates_records():
    annotated = dedup.apply_dedup([
        rec(name="Priya Sharma", company="StudioX",
            source_urls=["u-other"]),                      # fuzzy hit
        rec(name="Totally New", company="NewCo", source_urls=["u-new"]),
    ], LEDGER)
    assert annotated[0]["dedup_status"] == "possible-duplicate"
    assert annotated[0]["matched_ledger_name"] == "Priya Sharma"
    assert annotated[1]["dedup_status"] == "new"
