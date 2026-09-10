## Why

Recent sourcing runs have surfaced five quality problems that erode trust in the shortlist: candidates currently employed at the hiring company itself show up (e.g. Zyeta employees sourced for a Zyeta JD), `candidates.xlsx` still contains duplicate rows after dedup runs, non-Indian candidates with no relocation intent are being shortlisted, candidates already open to work aren't prioritized even though they respond faster, and there's no explicit guarantee that candidates from different JDs land in the same workbook rather than fragmenting across files. These are correctness gaps in filtering, dedup, and ranking, not new features - they need to be fixed before the pipeline can be trusted for daily use.

## What Changes

- Extract the hiring organization's name from the JD during intake and hard-filter out any candidate whose current employer normalizes to that same organization.
- Fix duplicate detection so records discovered within the same run are deduplicated against each other (not only against the existing ledger) before any of them are appended - this is what lets look-alike duplicates slip into `candidates.xlsx` today.
- Tighten the India hard filter so it only admits India-based candidates, or candidates located outside India who show explicit willingness to relocate to Bengaluru; candidates outside India with no relocation signal are eliminated (previously any non-India location signal was eliminated outright with no relocation carve-out).
- Capture an `open_to_work` signal per candidate (from public profile signals in Track A/portfolio discovery and from a recognized column in manual Track B exports) and use it as a ranking preference in top-N selection so open-to-work candidates are favored over equally-or-similarly scored candidates who aren't.
- Make explicit and regression-tested that all JDs append to the single shared `candidates.xlsx` ledger (current default behavior via `CPS_LEDGER_PATH`) rather than per-JD files, since this was reported as broken but the intended behavior was already single-workbook.

## Capabilities

### Modified Capabilities
- `jd-intake`: adds extraction of the hiring organization's name from the JD into the requirement profile, normalized the same way candidate employers are normalized for comparison.
- `candidate-discovery`: candidate record normalization gains an `open_to_work` field populated from available source signals.
- `candidate-shortlisting`: hard filters gain a same-employer-as-hiring-org exclusion; the India hard filter gains a Bengaluru-relocation carve-out for non-India-located candidates; cross-run/cross-track duplicate suppression is extended to also suppress duplicates within a single run's newly discovered batch; top-10 selection ranking gains an open-to-work preference.
- `shortlist-ledger`: ledger schema/append requirements are clarified to state explicitly that one shared workbook accumulates rows across all JDs (not one workbook per JD).

## Impact

- Affected code: `skill/candidate-sourcing/scripts/jd_parser.py` (hiring org extraction), `skill/candidate-sourcing/scripts/dedup.py` (intra-run dedup), `skill/candidate-sourcing/scripts/score_filters.py` (hiring-org exclusion, relocation carve-out), `skill/candidate-sourcing/scripts/candidate_schema.py` (open_to_work field), `skill/candidate-sourcing/scripts/topn.py` (ranking preference), `skill/candidate-sourcing/scripts/ingest.py` (open_to_work from manual exports), `skill/candidate-sourcing/scripts/pipeline.py` (wiring), `config/workflow.yaml` (new config knobs: relocation-signal patterns, open-to-work column mapping).
- No new external dependencies.
- Existing `candidates.xlsx` may already contain duplicate/ineligible rows from before this fix; those are not retroactively cleaned by this change (reviewers can mark them `rejected` manually) - this change only prevents new occurrences.
