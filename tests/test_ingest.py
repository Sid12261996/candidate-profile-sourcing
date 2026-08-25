"""Tests for ingest.py - format detection, mapping, quarantine flow (task 6.2).

Real stakeholder export formats land in task 6.1; these fixtures encode the
provisional signatures so the framework is proven before they arrive.
"""
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skill" / "candidate-sourcing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

ingest = importlib.import_module("ingest")

LINKEDIN_CSV = "\n".join([
    "First Name,Last Name,Current Title,Current Company,Location,Profile URL",
    'Priya,Sharma,"Lead Workspace Designer",StudioX,"Mumbai, MH",https://in.linkedin.com/in/priya',
    "Ravi,Kumar,BD Manager,GrowthCo,Bengaluru,https://in.linkedin.com/in/ravi",
]).encode()

NAUKRI_CSV = "\n".join([
    "Name,Resume Title,Current Employer,Total Experience,Location,Resume ID",
    'A. Fernandes,"Client Success Manager","ServiceHub Ltd","8 yrs",Goa,NK-10023',
]).encode()

MALFORMED_CSV = b"col_one,col_two\n1,2\n"


def test_linkedin_recruiter_signature_maps_records():
    records, info = ingest.ingest_bytes("export.csv", LINKEDIN_CSV)
    assert info["format"] == "linkedin-recruiter" and info["rows"] == 2
    priya = next(r for r in records if r["name"] == "Priya Sharma")
    assert priya["title"] == "Lead Workspace Designer"
    assert priya["company"] == "StudioX"
    assert priya["track"] == "platform-export"
    assert priya["profile_url"].endswith("/priya")


def test_naukri_resdex_signature_maps_experience_years():
    records, info = ingest.ingest_bytes("resdex.csv", NAUKRI_CSV)
    assert info["format"] == "naukri-resdex"
    assert records[0]["experience_years"] == 8
    assert records[0]["profile_url"] == "naukri:NK-10023"


def test_unknown_format_raises():
    with pytest.raises(ingest.UnknownFormatError):
        ingest.ingest_bytes("weird.csv", MALFORMED_CSV)


def test_inbox_flow_good_processed_bad_quarantined():  # task 6.2 scenario
    files = {"a-good.csv": LINKEDIN_CSV, "b-bad.csv": MALFORMED_CSV,
             "c-good.csv": NAUKRI_CSV}
    processed, quarantined = [], []

    summary = ingest.ingest_inbox(
        list_names_fn=lambda: sorted(files),
        read_fn=lambda n: files[n],
        mark_processed_fn=lambda n: processed.append(n),
        quarantine_fn=lambda n: quarantined.append(n),
    )

    assert {i["file"] for i in summary["ingested"]} == {"a-good.csv", "c-good.csv"}
    assert summary["quarantined"][0]["file"] == "b-bad.csv"
    assert "reason" in summary["quarantined"][0]
    assert sorted(processed) == ["a-good.csv", "c-good.csv"]
    assert quarantined == ["b-bad.csv"]
    # all inbox files were attempted (bad one did not stop processing)
    assert len(summary["ingested"]) + len(summary["quarantined"]) == 3


def test_all_platform_exports_share_track_value():
    for blob in (LINKEDIN_CSV, NAUKRI_CSV):
        records, _ = ingest.ingest_bytes("f.csv", blob)
        assert all(r["track"] == "platform-export" for r in records)
