#!/usr/bin/env python3
"""
Hawkeye Solutions — Recruitment-sector lead pull from Companies House

Discovers every UK company registered under recruitment SIC codes, then
enriches each with its latest filed accounts category (the only free,
automatable size proxy Companies House offers) and registered address.

No size filtering happens here — every active company in scope is kept,
tagged with a size_band so sorting/prioritising happens downstream (in the
CRM or a later scoring step), not during collection.

Usage:
    export COMPANIES_HOUSE_API_KEY=your_key_here
    python3 companies_house.py                 # run (resumes if interrupted)
    python3 companies_house.py --fresh          # ignore saved progress, start over

Get a free key at: https://developer.company-information.service.gov.uk/
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

# ── Configuration ───────────────────────────────────────────────────────────

API_BASE      = "https://api.company-information.service.gov.uk"
SIC_CODES     = ["78100", "78200", "78300"]  # placement / temp staffing / HR provision
PAGE_SIZE     = 500          # advanced search page size (max allowed: 5000)
TIMEOUT       = 30           # seconds per request
RETRY_DELAYS  = [10, 30, 90, 300]  # backoff on 429 / 5xx
REQUEST_DELAY = 0.15         # polite pause between calls (well under 600/5min)

# The advanced search endpoint 500s once start_index goes past ~10,000 into a
# single result set (a search-index depth limit, not a transient error — it
# will never succeed no matter how many times it's retried). Worked around by
# searching one incorporation-date window at a time, recursively halving any
# window whose result count is still over the safe threshold below.
MAX_WINDOW_RESULTS = 9000
EARLIEST_INCORPORATION = date(1900, 1, 1)

OUTPUT_FILE   = Path(__file__).parent / "companies_house.json"
STATE_FILE    = Path(__file__).parent / "companies_house_state.json"
LOG_FILE      = Path(__file__).parent / "companies_house.log"

# Maps filed accounts type -> a rough size band.
# "full" and "total-exemption-full" predate the small/medium accounts regime
# (pre-~2013) and could be either — left as unknown rather than guessed.
SIZE_BAND = {
    "micro-entity":            "micro",
    "small":                    "small",
    "medium":                   "medium",
    "group":                    "large",
    "dormant":                  "dormant",
    "audited-abridged":         "small",
    "unaudited-abridged":       "small",
    "full":                     "unknown-full",
    "total-exemption-full":     "unknown-full",
    "no-accounts-filed":        "unknown",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("companies_house")


def api_key() -> str:
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not key:
        log.error(
            "COMPANIES_HOUSE_API_KEY not set. Get a free key at "
            "https://developer.company-information.service.gov.uk/ and "
            "export COMPANIES_HOUSE_API_KEY=... before running."
        )
        sys.exit(1)
    return key


def request_with_retry(session: requests.Session, url: str, params: dict | None = None) -> dict | None:
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            log.warning("Retry %d — waiting %ds", attempt - 1, delay)
            time.sleep(delay)
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            log.warning("Request failed: %s", e)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("%s %s — will retry", resp.status_code, resp.reason)
            continue
        log.error("Unexpected %s for %s: %s", resp.status_code, url, resp.text[:300])
        return None
    log.error("Giving up on %s after retries", url)
    return None


def search_count(session: requests.Session, sic_param: str, date_from: date, date_to: date) -> int:
    data = request_with_retry(
        session,
        f"{API_BASE}/advanced-search/companies",
        params={
            "sic_codes": sic_param,
            "company_status": "active",
            "incorporated_from": date_from.isoformat(),
            "incorporated_to": date_to.isoformat(),
            "size": 1,
            "start_index": 0,
        },
    )
    if not data:
        return 0
    items = data.get("items", [])
    return data.get("hits", data.get("total_results", len(items)))


def page_through_window(session: requests.Session, sic_param: str, date_from: date, date_to: date, total: int) -> list[str]:
    numbers: list[str] = []
    start_index = 0
    while start_index < total:
        data = request_with_retry(
            session,
            f"{API_BASE}/advanced-search/companies",
            params={
                "sic_codes": sic_param,
                "company_status": "active",
                "incorporated_from": date_from.isoformat(),
                "incorporated_to": date_to.isoformat(),
                "size": PAGE_SIZE,
                "start_index": start_index,
            },
        )
        if not data:
            log.error(
                "Giving up on window %s..%s at start_index=%d — %d companies from "
                "this window will be MISSING from the results",
                date_from, date_to, start_index, total - len(numbers),
            )
            break
        items = data.get("items", [])
        for item in items:
            num = item.get("company_number")
            if num:
                numbers.append(num)
        start_index += PAGE_SIZE
        if not items:
            break
        time.sleep(REQUEST_DELAY)
    return numbers


def discover_window(session: requests.Session, sic_param: str, date_from: date, date_to: date, depth: int = 0) -> list[str]:
    total = search_count(session, sic_param, date_from, date_to)
    if total == 0:
        return []
    if total > MAX_WINDOW_RESULTS and date_to > date_from and depth < 50:
        mid = date_from + (date_to - date_from) // 2
        log.info(
            "Window %s..%s has %d results (>%d) — splitting at %s",
            date_from, date_to, total, MAX_WINDOW_RESULTS, mid,
        )
        left = discover_window(session, sic_param, date_from, mid, depth + 1)
        right = discover_window(session, sic_param, mid + timedelta(days=1), date_to, depth + 1)
        return left + right
    if total > MAX_WINDOW_RESULTS:
        log.warning(
            "Window %s..%s still has %d results after max split depth — "
            "paginating as far as possible, some companies may be missing",
            date_from, date_to, total,
        )
    numbers = page_through_window(session, sic_param, date_from, date_to, total)
    log.info("Window %s..%s: %d/%d companies collected", date_from, date_to, len(numbers), total)
    return numbers


def discover_company_numbers(session: requests.Session) -> list[str]:
    """Advanced search across all SIC codes at once, split into incorporation-date
    windows small enough to avoid the search API's deep-pagination limit."""
    sic_param = ",".join(SIC_CODES)
    numbers = discover_window(session, sic_param, EARLIEST_INCORPORATION, date.today())
    # De-dupe in case a boundary date was double-counted across adjacent windows
    return list(dict.fromkeys(numbers))


def fetch_profile(session: requests.Session, company_number: str) -> dict | None:
    return request_with_retry(session, f"{API_BASE}/company/{company_number}")


def to_record(profile: dict) -> dict:
    address = profile.get("registered_office_address", {}) or {}
    accounts_type = (profile.get("accounts", {}) or {}).get("last_accounts", {}).get("type")
    return {
        "company_number": profile.get("company_number"),
        "company_name": profile.get("company_name"),
        "company_status": profile.get("company_status"),
        "sic_codes": profile.get("sic_codes", []),
        "incorporation_date": profile.get("date_of_creation"),
        "address_line_1": address.get("address_line_1"),
        "address_line_2": address.get("address_line_2"),
        "locality": address.get("locality"),
        "region": address.get("region"),
        "postal_code": address.get("postal_code"),
        "accounts_type": accounts_type,
        "size_band": SIZE_BAND.get(accounts_type, "unknown"),
        "company_url": f"https://find-and-update.company-information.service.gov.uk/company/{profile.get('company_number')}",
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"discovered": [], "done": [], "records": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true", help="ignore saved progress and start over")
    args = parser.parse_args()

    session = requests.Session()
    session.auth = (api_key(), "")

    state = {} if args.fresh else load_state()
    state.setdefault("discovered", [])
    state.setdefault("done", [])
    state.setdefault("records", {})

    if not state["discovered"]:
        log.info("Discovering companies for SIC codes %s …", ", ".join(SIC_CODES))
        state["discovered"] = discover_company_numbers(session)
        save_state(state)
        log.info("Discovery complete: %d companies found", len(state["discovered"]))

    done = set(state["done"])
    todo = [n for n in state["discovered"] if n not in done]
    log.info("Enriching %d companies (%d already done)", len(todo), len(done))

    for i, number in enumerate(todo, start=1):
        profile = fetch_profile(session, number)
        if profile:
            state["records"][number] = to_record(profile)
        state["done"].append(number)
        if i % 25 == 0:
            save_state(state)
            log.info("Progress: %d/%d enriched", i, len(todo))
        time.sleep(REQUEST_DELAY)

    save_state(state)
    records = list(state["records"].values())
    OUTPUT_FILE.write_text(json.dumps(records, indent=2))
    log.info("Done. %d companies written to %s", len(records), OUTPUT_FILE)

    bands = {}
    for r in records:
        bands[r["size_band"]] = bands.get(r["size_band"], 0) + 1
    for band, count in sorted(bands.items(), key=lambda x: -x[1]):
        log.info("  %-14s %d", band, count)


if __name__ == "__main__":
    main()
