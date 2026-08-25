"""Top-N selection among non-excluded scored candidates (task 7.3)."""


def select_top_n(scored_records: list[dict], excluded_urls: set[str] | None = None,
                 n: int = 10) -> list[dict]:
    """Highest-scoring n records not already in the ledger.

    - records already shortlisted/excluded are dropped BEFORE ranking
      (spec: they never occupy a slot)
    - ties break alphabetically by name for deterministic runs
    - fewer than n qualified candidates -> all of them flow through
    """
    excluded_urls = {u for u in (excluded_urls or set()) if u}
    eligible = []
    for rec in scored_records:
        urls = set(rec.get("source_urls") or [])
        if rec.get("profile_url"):
            urls.add(rec["profile_url"])
        if rec.get("excluded") or (urls & excluded_urls):
            continue
        eligible.append(rec)

    eligible.sort(key=lambda r: (-r.get("score", 0), r.get("name") or ""))
    return eligible[:n]
