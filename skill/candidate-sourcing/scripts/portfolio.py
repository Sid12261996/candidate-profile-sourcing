"""Track A supplement: public portfolio discovery for design roles (task 5.3).

Gated by workflow.yaml role_families.<family>.portfolio_sources - only design
families run these queries (spec scenario: non-design JD skips portfolios).

Implementation note: Behance/Dribbble are queried through the SAME public
search() boundary using site-restricted queries rather than scraping the
portfolio sites directly. This reuses one verified, swappable backend and
avoids brittle DOM parsing of those sites.
"""
from __future__ import annotations

import search
from candidate_schema import make_record
from config_loader import load_config

_PORTFOLIO_SITES = ("behance.net", "dribbble.com")


def portfolio_enabled(profile: dict, cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    family = profile.get("role_family")
    if not family:
        return False
    spec = cfg.get("role_families", {}).get(family, {})
    return bool(spec.get("portfolio_sources"))


def build_queries(profile: dict) -> list[str]:
    role = profile.get("title") or "designer"
    queries = [f'site:{site} "{role}" India' for site in _PORTFOLIO_SITES]
    for loc in profile.get("locations") or []:
        queries.append(f'site:{_PORTFOLIO_SITES[0]} "{role}" "{loc}"')
    return queries


def _display_name(result_title: str, site: str) -> str | None:
    """Behance results often look like 'Project Name on Behance' - keep as label."""
    label = result_title.split(" on ")[0].strip()
    return label or None


def run_portfolio_discovery(profile: dict, cfg: dict | None = None,
                            search_fn=search.search) -> tuple[list[dict], list[str]]:
    """Portfolio records + degradation errors; empty when family not design."""
    if not portfolio_enabled(profile, cfg):
        return [], []
    cfg = cfg or load_config()
    cap = int(cfg["search_backend"]["max_queries_per_jd_per_run"]) // 2 or 1
    records_by_url, errors = {}, []

    for query in build_queries(profile)[:cap]:
        try:
            for result in search_fn(query):
                url = result.get("url", "")
                if not any(s in url for s in _PORTFOLIO_SITES):
                    continue
                site = next(s for s in _PORTFOLIO_SITES if s in url)
                rec = make_record(
                    name=_display_name(result.get("title", ""), site),
                    title=result.get("title", ""),
                    track="portfolio",
                    source_urls=[url],
                )
                rec["snippet"] = result.get("snippet", "")
                records_by_url[url] = rec
        except search.SearchBackendError as exc:
            errors.append(str(exc))

    return sorted(records_by_url.values(), key=lambda r: r["profile_url"]), errors
