#!/usr/bin/env python3
"""
Hawkeye Solutions — website enrichment for Tier 1 leads

For every Tier 1 lead with a contact email, the domain IS the company's
website — no search needed. This visits each one and pulls:
  - title / meta description (almost always states the company's
    specialism — exactly the "what sector do they actually work in" signal)
  - any mailto:/tel: links found on the page, as bonus contact info beyond
    the single named contact we already have

Tier 2 isn't covered here — those leads have no email yet, so there's no
domain to start from. Separate problem, see leads/README notes/conversation.

Usage:
    python3 enrich_websites.py           # resumes if interrupted
    python3 enrich_websites.py --fresh    # ignore saved progress
"""

import argparse
import json
import logging
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests

SCORED_FILE = Path(__file__).parent / "scored_leads.json"
OUTPUT_FILE = Path(__file__).parent / "website_enrichment.json"
STATE_FILE  = Path(__file__).parent / "enrich_websites_state.json"
LOG_FILE    = Path(__file__).parent / "enrich_websites.log"

TIMEOUT = 15
REQUEST_DELAY = 0.5
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HawkeyeLeadResearch/1.0)"}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk", "outlook.com",
    "live.co.uk", "live.com", "yahoo.com", "yahoo.co.uk", "icloud.com", "aol.com",
    "btinternet.com", "virginmedia.com", "sky.com", "talktalk.net", "msn.com",
    "me.com", "mail.com",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("enrich_websites")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.links = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            if name in ("description", "og:description") and not self.meta_description:
                self.meta_description = (attrs.get("content") or "").strip()
        elif tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def domain_from_email(email: str) -> str | None:
    if "@" not in email:
        return None
    domain = email.split("@", 1)[1].strip().lower()
    if domain in FREE_EMAIL_DOMAINS:
        return None
    return domain


def extract_contacts(links: list[str]) -> tuple[list[str], list[str]]:
    emails, phones = [], []
    for href in links:
        if href.startswith("mailto:"):
            addr = href[7:].split("?")[0].strip().lower()
            if addr:
                emails.append(addr)
        elif href.startswith("tel:"):
            num = href[4:].split("?")[0].strip()
            if num:
                phones.append(num)
    return list(dict.fromkeys(emails)), list(dict.fromkeys(phones))


def fetch_site(domain: str) -> dict:
    for scheme in ("https://", "http://"):
        url = f"{scheme}{domain}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if resp.status_code >= 400:
                continue
            parser = PageParser()
            parser.feed(resp.text[:200_000])  # cap — only need the head/nav, not the whole page
            emails, phones = extract_contacts(parser.links)
            return {
                "domain": domain,
                "fetched_ok": True,
                "final_url": resp.url,
                "title": parser.title.strip()[:200],
                "meta_description": parser.meta_description[:400],
                "extra_emails": emails,
                "extra_phones": phones,
                "error": "",
            }
        except requests.RequestException as e:
            last_error = str(e)
            continue
    return {
        "domain": domain, "fetched_ok": False, "final_url": "", "title": "",
        "meta_description": "", "extra_emails": [], "extra_phones": [],
        "error": last_error if "last_error" in dir() else "unreachable",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    leads = json.loads(SCORED_FILE.read_text())
    tier1 = [l for l in leads if l["tier"] == 1 and l.get("contact_email")]

    domains = {}
    for lead in tier1:
        d = domain_from_email(lead["contact_email"])
        if d:
            domains[d] = True
    domains = sorted(domains.keys())
    log.info("%d Tier 1 leads with an email -> %d unique company domains to visit", len(tier1), len(domains))

    state = {} if args.fresh else (json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {})

    for i, domain in enumerate(domains, start=1):
        if domain in state:
            continue
        result = fetch_site(domain)
        state[domain] = result
        if i % 25 == 0:
            STATE_FILE.write_text(json.dumps(state))
            log.info("Progress: %d/%d", i, len(domains))
        time.sleep(REQUEST_DELAY)

    STATE_FILE.write_text(json.dumps(state))
    OUTPUT_FILE.write_text(json.dumps(state, indent=2))

    ok = sum(1 for v in state.values() if v["fetched_ok"])
    with_desc = sum(1 for v in state.values() if v.get("meta_description"))
    log.info("Done. %d/%d domains fetched OK, %d had a usable description", ok, len(state), with_desc)


if __name__ == "__main__":
    main()
