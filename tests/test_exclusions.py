"""Tests for exclusions.py - zero-score registry (task 5.1)."""
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

exclusions = importlib.import_module("exclusions")


def test_append_load_round_trip(tmp_path):
    path = tmp_path / "exclusions.json"
    assert exclusions.load(path) == [] and exclusions.urls(path) == set()

    added = exclusions.append(
        [{"url": "u://a", "jd": "jd1", "date": "2026-08-26"},
         {"url": "u://b", "jd": "jd2"}],
        path)
    assert added == 2
    entries = exclusions.load(path)
    assert entries[0] == {"url": "u://a", "jd": "jd1", "date": "2026-08-26"}
    assert entries[1]["date"]                       # defaulted to today
    assert exclusions.urls(path) == {"u://a", "u://b"}


def test_append_dedupes_same_url_jd_pair(tmp_path):
    path = tmp_path / "exclusions.json"
    exclusions.append([{"url": "u://a", "jd": "jd1"}], path)
    assert exclusions.append([{"url": "u://a", "jd": "jd1"}], path) == 0
    assert len(exclusions.load(path)) == 1


def test_corrupt_or_missing_file_degrades_to_empty(tmp_path):
    path = tmp_path / "exclusions.json"
    path.write_text("{not json")
    assert exclusions.load(path) == [] and exclusions.urls(path) == set()


def test_split_records_skips_registered_before_scoring():
    records = [
        {"name": "Fresh", "profile_url": "u://fresh", "source_urls": ["u://fresh"]},
        {"name": "Zerod", "profile_url": "u://zero", "source_urls": ["u://zero"]},
    ]
    passed, dropped = exclusions.split_records(records, {"u://zero"})
    assert [r["name"] for r in passed] == ["Fresh"]
    assert [r["name"] for r in dropped] == ["Zerod"]
