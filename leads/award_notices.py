#!/usr/bin/env python3
"""
Hawkeye Solutions — recruitment-sector award notices from Find a Tender

The main tender pipeline deliberately filters OUT award/contract notices
(it only wants to show OPEN opportunities on the public tender board). For
lead-sourcing that's exactly backwards: an award notice names the company
that just WON a real public-sector recruitment contract — stronger proof
of active business than framework membership, which only proves
eligibility. This is a separate, smaller scrape of the same API with the
opposite filter.

Covers the last 24 months by default (recency matters more here than for
the main board — we care who's winning *now*).

Usage:
    python3 award_notices.py                 # resumes if interrupted
    python3 award_notices.py --months 36      # wider window
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API_BASE      = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
TIMEOUT       = 90
MAX_PAGES     = 500
PAGE_DELAY    = 1.5
RETRY_DELAYS  = [60, 120, 300]
MONTH_DELAY   = 5

RECRUITMENT_CPV_PREFIX = "796"  # 79600000-79699999, same mapping the main pipeline uses

OUTPUT_FILE = Path(__file__).parent / "award_notices.json"
STATE_FILE  = Path(__file__).parent / "award_notices_state.json"
LOG_FILE    = Path(__file__).parent / "award_notices.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("award_notices")


def month_ranges(start: datetime, end: datetime) -> list[tuple[str, str]]:
    chunks = []
    cur = start
    while cur < end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        chunks.append((cur.strftime("%Y-%m-%dT%H:%M:%S"), min(nxt, end).strftime("%Y-%m-%dT%H:%M:%S")))
        cur = nxt
    return chunks


def fetch_page(url: str, params: dict | None) -> dict | None:
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            log.warning("Retry %d — waiting %ds", attempt - 1, delay)
            time.sleep(delay)
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            log.warning("Request failed: %s", e)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("%s — will retry", resp.status_code)
            continue
        log.error("Unexpected %s for %s", resp.status_code, url)
        return None
    return None


def fetch_window(date_from: str, date_to: str) -> list[dict]:
    releases, next_url, page = [], API_BASE, 0
    params = {"updatedFrom": date_from, "updatedTo": date_to, "limit": 100}
    while next_url and page < MAX_PAGES:
        page += 1
        pkg = fetch_page(next_url, params if page == 1 else None)
        if not pkg:
            break
        releases.extend(pkg.get("releases", []))
        next_url = pkg.get("links", {}).get("next", "")
        if next_url:
            time.sleep(PAGE_DELAY)
    return releases


def is_recruitment_cpv(classification: dict | None) -> bool:
    if not classification:
        return False
    cpv = (classification.get("id") or "").split("-")[0].strip()
    return cpv.startswith(RECRUITMENT_CPV_PREFIX)


def extract_award_leads(release: dict) -> list[dict]:
    if "award" not in release.get("tag", []):
        return []
    tender = release.get("tender", {})
    classification = tender.get("classification")
    if not is_recruitment_cpv(classification):
        items = tender.get("items", [])
        if not any(is_recruitment_cpv(i.get("classification")) for i in items):
            return []

    parties_by_id = {p["id"]: p for p in release.get("parties", []) if p.get("id")}
    buyer = release.get("buyer", {}).get("name", "")
    notice_url = ""
    for doc in tender.get("documents", []):
        if doc.get("documentType") == "awardNotice":
            notice_url = doc.get("url", "")
            break

    supplier_ids = set()
    for award in release.get("awards", []):
        for s in award.get("suppliers", []):
            if s.get("id"):
                supplier_ids.add(s["id"])

    leads = []
    for sid in supplier_ids:
        party = parties_by_id.get(sid, {})
        if "supplier" not in party.get("roles", []):
            continue
        address = party.get("address", {})
        leads.append({
            "supplier_name": party.get("name", ""),
            "supplier_id": sid,
            "contact_email": (party.get("contactPoint") or {}).get("email", ""),
            "website": (party.get("details") or {}).get("url", ""),
            "locality": address.get("locality", ""),
            "postal_code": address.get("postalCode", ""),
            "buyer": buyer,
            "tender_title": tender.get("title", ""),
            "award_date": release.get("date", ""),
            "notice_url": notice_url,
            "ocid": release.get("ocid", ""),
        })
    return leads


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"done_months": [], "leads_by_supplier": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    start = (now.replace(day=1) - timedelta(days=30 * args.months)).replace(day=1)
    chunks = month_ranges(start, now)

    state = {"done_months": [], "leads_by_supplier": {}} if args.fresh else load_state()
    done = set(state["done_months"])

    for date_from, date_to in chunks:
        key = date_from[:7]
        if key in done:
            continue
        log.info("Fetching %s..%s", date_from, date_to)
        releases = fetch_window(date_from, date_to)
        found_this_month = 0
        for release in releases:
            for lead in extract_award_leads(release):
                sid = lead["supplier_id"]
                existing = state["leads_by_supplier"].get(sid)
                if not existing or lead["award_date"] > existing["award_date"]:
                    state["leads_by_supplier"][sid] = lead
                    found_this_month += 1
        state["done_months"].append(key)
        save_state(state)
        log.info("  %s: %d releases scanned, %d recruitment award leads found/updated", key, len(releases), found_this_month)
        time.sleep(MONTH_DELAY)

    leads = list(state["leads_by_supplier"].values())
    OUTPUT_FILE.write_text(json.dumps(leads, indent=2))
    with_email = sum(1 for l in leads if l["contact_email"])
    log.info("Done. %d unique recruitment-contract winners written to %s (%d with an email)", len(leads), OUTPUT_FILE, with_email)


if __name__ == "__main__":
    main()
