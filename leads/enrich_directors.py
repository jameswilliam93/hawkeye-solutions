#!/usr/bin/env python3
"""
Hawkeye Solutions — fill in a real contact name for Tier 2 leads

Companies House publishes director names for free (no scraping) via its
officers endpoint. This pulls the most relevant active director for every
Tier 2 lead in scored_leads.json and fills in contact_name — a genuine,
authoritative name to address outreach to, ahead of any website/email
enrichment later.

Picks, in order of preference: an active (not resigned) officer with role
"director" over "secretary"/other roles, and the most recently appointed
if there's more than one active director.

Usage:
    export COMPANIES_HOUSE_API_KEY=your_key_here
    python3 enrich_directors.py              # resumes if interrupted
    python3 enrich_directors.py --fresh       # ignore saved progress
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

API_BASE      = "https://api.company-information.service.gov.uk"
TIMEOUT       = 30
RETRY_DELAYS  = [10, 30, 90, 300]
REQUEST_DELAY = 0.15

SCORED_FILE = Path(__file__).parent / "scored_leads.json"
STATE_FILE  = Path(__file__).parent / "enrich_directors_state.json"
LOG_FILE    = Path(__file__).parent / "enrich_directors.log"

DIRECTOR_ROLES = {"director", "corporate-director", "nominee-director"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("enrich_directors")


def api_key() -> str:
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not key:
        log.error("COMPANIES_HOUSE_API_KEY not set.")
        sys.exit(1)
    return key


def request_with_retry(session: requests.Session, url: str) -> dict | None:
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            log.warning("Retry %d — waiting %ds", attempt - 1, delay)
            time.sleep(delay)
        try:
            resp = session.get(url, timeout=TIMEOUT)
        except requests.RequestException as e:
            log.warning("Request failed: %s", e)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        if resp.status_code in (429, 500, 502, 503, 504):
            log.warning("%s %s — will retry", resp.status_code, resp.reason)
            continue
        log.error("Unexpected %s for %s", resp.status_code, url)
        return None
    log.error("Giving up on %s after retries", url)
    return None


def format_name(ch_name: str) -> str:
    """Companies House gives 'SURNAME, Forename Middle' — flip to 'Forename Middle Surname'."""
    if "," not in ch_name:
        return ch_name.strip().title()
    surname, _, rest = ch_name.partition(",")
    return f"{rest.strip().title()} {surname.strip().title()}"


def pick_best_officer(officers: list[dict]) -> dict | None:
    active = [o for o in officers if not o.get("resigned_on")]
    if not active:
        return None
    directors = [o for o in active if o.get("officer_role") in DIRECTOR_ROLES]
    pool = directors or active
    pool.sort(key=lambda o: o.get("appointed_on") or "", reverse=True)
    return pool[0]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"done": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    session = requests.Session()
    session.auth = (api_key(), "")

    leads = json.loads(SCORED_FILE.read_text())
    tier2 = [l for l in leads if l["tier"] == 2]
    log.info("%d Tier 2 leads to enrich", len(tier2))

    state = {"done": {}} if args.fresh else load_state()

    for i, lead in enumerate(tier2, start=1):
        number = lead["company_number"]
        if number in state["done"]:
            lead["contact_name"] = state["done"][number] or ""
            continue
        data = request_with_retry(session, f"{API_BASE}/company/{number}/officers")
        name = ""
        if data:
            best = pick_best_officer(data.get("items", []))
            if best:
                name = format_name(best["name"])
        state["done"][number] = name
        lead["contact_name"] = name
        if i % 25 == 0:
            save_state(state)
            log.info("Progress: %d/%d", i, len(tier2))
        time.sleep(REQUEST_DELAY)

    save_state(state)
    SCORED_FILE.write_text(json.dumps(leads, indent=2))

    with_name = sum(1 for l in tier2 if l["contact_name"])
    log.info("Done. %d/%d Tier 2 leads now have a director name", with_name, len(tier2))


if __name__ == "__main__":
    main()
