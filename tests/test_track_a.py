"""Tests for Track A: search boundary, xray, portfolio, degradation (tasks 5.1-5.4)."""
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

search_mod = importlib.import_module("search")
xray = importlib.import_module("xray")
portfolio = importlib.import_module("portfolio")
candidate_schema = importlib.import_module("candidate_schema")

CFG = {
    "role_families": {
        "workspace_designer": {"title_patterns": ["workspace designer"],
                               "portfolio_sources": True},
        "business_development": {"title_patterns": ["business development"],
                                 "portfolio_sources": False},
    },
    "defaults": {},
    "search_backend": {
        "provider": "searxng",
        "base_url_env": "SEARXNG_BASE_URL",
        "fallback": "duckduckgo",
        "max_queries_per_jd_per_run": 4,
    },
}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    for mod in (search_mod, xray, portfolio):
        monkeypatch.setattr(mod, "load_config", lambda: CFG)


PROFILE = {"title": "Workspace Designer", "role_family": "workspace_designer",
           "locations": ["mumbai"]}


# ---------------------------------------------------------------- search()

def test_searxng_json_parsing(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"title": "A - Designer | LinkedIn",
                 "url": "https://in.linkedin.com/in/a", "content": "snip"}]}
    monkeypatch.setattr(search_mod.requests, "get",
                        lambda *a, **k: R())
    out = search_mod.search("q")
    assert out == [{"title": "A - Designer | LinkedIn",
                    "url": "https://in.linkedin.com/in/a", "snippet": "snip"}]


def test_fallback_when_searxng_down(monkeypatch):
    import requests as real_requests

    def boom(*a, **k):
        raise real_requests.ConnectionError("down")
    monkeypatch.setattr(search_mod.requests, "get", boom)

    class DDGS:
        def __init__(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, q, max_results=5):
            return [{"title": "t", "href": "u", "body": "b"}]
    import types
    fake_mod = types.ModuleType("duckduckgo_search")
    fake_mod.DDGS = DDGS
    monkeypatch.setitem(__import__("sys").modules, "duckduckgo_search", fake_mod)

    out = search_mod.search("q")
    assert out == [{"title": "t", "url": "u", "snippet": "b"}]


def test_all_backends_fail_raises(monkeypatch):
    import requests as real_requests
    monkeypatch.setattr(search_mod.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(real_requests.ConnectionError()))
    with pytest.raises(search_mod.SearchBackendError):
        search_mod.search("q")


# ------------------------------------------------------------------ xray

def test_build_queries_respects_location_and_cap():
    q = xray.build_queries(PROFILE)
    assert q == ['site:linkedin.com/in "Workspace Designer" "mumbai"']
    big = dict(PROFILE, locations=["a", "b", "c", "d", "e"])
    assert len(xray.build_queries(big)) <= 4  # capped by max_queries_per_jd_per_run


def test_parse_result_extracts_name_headline():
    rec = xray.parse_result({
        "title": "Priya Sharma - Lead Workspace Designer - StudioX | LinkedIn",
        "url": "https://in.linkedin.com/in/priya-sharma",
        "snippet": "10 yrs",
    })
    assert rec["name"] == "Priya Sharma"
    assert rec["title"] == "Lead Workspace Designer - StudioX"
    assert rec["track"] == "xray"
    assert rec["profile_url"].endswith("/priya-sharma")


def test_parse_result_ignores_non_profile_urls():
    assert xray.parse_result({"title": "Jobs", "url": "https://linkedin.com/jobs"}) is None


def test_run_track_a_merges_duplicates_across_queries():
    r1 = {"title": "Priya S - Designer | LinkedIn", "url": "https://in.linkedin.com/in/priya"}
    r2 = {"title": "Ravi K - Designer | LinkedIn", "url": "https://in.linkedin.com/in/ravi"}
    calls = []
    def fake_search(query):
        calls.append(query)
        return [r1] if "mumbai" in query else [r2, r1]
    recs, errs = xray.run_track_a(
        dict(PROFILE, locations=["mumbai", "pune"]), search_fn=fake_search)
    urls = [r["profile_url"] for r in recs]
    assert len(urls) == len(set(urls)) and len(recs) == 2 and not errs


def test_graceful_degradation_backend_failure(monkeypatch):  # task 5.4
    def failing(query):
        raise search_mod.SearchBackendError(f"all search backends failed for: {query!r}")
    recs, errs = xray.run_track_a(PROFILE, search_fn=failing)
    assert recs == [] and len(errs) == 1   # zero candidates, error noted, no exception


# -------------------------------------------------------------- portfolio

def test_portfolio_gated_to_design_families():  # task 5.3 scenarios
    assert portfolio.portfolio_enabled(PROFILE) is True
    bd = {"title": "BD Manager", "role_family": "business_development"}
    assert portfolio.portfolio_enabled(bd) is False


def test_portfolio_skips_for_non_design():
    recs, errs = portfolio.run_portfolio_discovery(
        {"title": "BD Manager", "role_family": "business_development"},
        search_fn=lambda q: pytest.fail("must not query"),
    )
    assert recs == [] and errs == []


def test_portfolio_keeps_only_site_matches():
    results = [
        {"title": "Office Makeover on Behance", "url": "https://behance.net/gallery/x", "snippet": ""},
        {"title": "Unrelated blog", "url": "https://blog.example.com/x", "snippet": ""},
    ]
    recs, _ = portfolio.run_portfolio_discovery(PROFILE, search_fn=lambda q: results)
    assert len(recs) == 1 and recs[0]["track"] == "portfolio"


def test_record_schema_rejects_unknown_track():
    with pytest.raises(ValueError):
        candidate_schema.make_record(track="linkedin")
