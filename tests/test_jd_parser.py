"""Tests for jd_parser.py - full JD, partial JD, defaults behavior (task 4.1)."""
import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

jd_parser = importlib.import_module("jd_parser")

FULL_JD = """# Senior Workspace Designer

We are looking for a senior workspace designer with 6+ years of experience,
based in Mumbai.

## Must have
- 6+ years designing modern office workspaces
- Proficiency in AutoCAD and SketchUp
- Portfolio of completed commercial projects

## Preferred
- LEED accreditation
- Experience with client-facing presentations

Weights: portfolio=0.5 experience=0.3 client_communication=0.2
"""

PARTIAL_JD = """# Client Success Officer

Own onboarding for our SMB accounts and reduce churn.
"""


def test_full_jd_extracts_all_fields():
    p = jd_parser.parse_jd(FULL_JD)
    assert p["title"] == "Senior Workspace Designer"
    assert p["role_family"] == "workspace_designer"
    assert p["seniority"] == "senior"
    assert p["experience_band_years"]["min"] == 6
    assert p["experience_band_years"]["max"] is None
    assert "mumbai" in p["locations"]
    assert any("AutoCAD" in item for item in p["must_have"])
    assert any("LEED" in item for item in p["preferred"])
    assert p["scoring_weights"]["portfolio"] == 0.5


def test_partial_jd_leaves_fields_unspecified():
    p = jd_parser.parse_jd(PARTIAL_JD)
    assert p["title"] == "Client Success Officer"
    assert p["role_family"] == "client_success"
    assert p["seniority"] is None                      # never invented
    assert p["experience_band_years"]["min"] is None
    assert p["locations"] == []
    assert p["must_have"] == []
    assert p["scoring_weights"] is None


def test_defaults_fill_unspecified_only():
    cfg = {
        "role_families": {
            "client_success": {"title_patterns": ["client success"],
                               "portfolio_sources": False},
        },
        "defaults": {
            "experience_band_years": {"min": 4, "max": None},
            "locations": ["bengaluru"],
        },
    }
    raw = jd_parser.parse_jd(PARTIAL_JD, cfg)
    eff = jd_parser.apply_defaults(raw, cfg)
    assert eff["experience_band_years"]["min"] == 4     # default applied
    assert eff["locations"] == ["bengaluru"]
    # specified values are never overridden
    full_raw = jd_parser.parse_jd(FULL_JD, cfg)
    full_eff = jd_parser.apply_defaults(full_raw, cfg)
    assert full_eff["experience_band_years"]["min"] == 6
    assert "mumbai" in full_eff["locations"]


def test_seniority_lead_beats_senior():
    text = "# Lead Workspace Designer\nYou are senior and will be leading a team in Pune.\n- 8+ years required"
    p = jd_parser.parse_jd(text)
    assert p["seniority"] == "lead"


def test_location_normalisation():
    p = jd_parser.parse_jd("# X\nBased in Bangalore / Bengaluru hybrid. 3-5 years.")
    assert p["locations"].count("bengaluru") == 1 and "bangalore" not in p["locations"]
    assert p["experience_band_years"] == {"min": 3, "max": 5}
