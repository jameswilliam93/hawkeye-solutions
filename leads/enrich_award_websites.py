#!/usr/bin/env python3
"""
Hawkeye Solutions — website enrichment for award-notice winners

Same technique as enrich_websites.py (domain derived from their own email,
no search needed), applied to award_notices.json leads instead of Tier 1
CCS leads. Results merge into the same website_enrichment.json file, so
score_leads.py picks them up automatically via award_site_info().

Usage:
    python3 enrich_award_websites.py              # all award leads with an email
    python3 enrich_award_websites.py --new-only    # just leads/new_award_leads.json
                                                     # (what a check-in run after
                                                     # `award_notices.py` should use)
"""

import argparse
import json
import logging
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

AWARDS_FILE     = Path(__file__).parent / "award_notices.json"
NEW_AWARDS_FILE = Path(__file__).parent / "new_award_leads.json"
WEBSITE_FILE    = Path(__file__).parent / "website_enrichment.json"
LOG_FILE        = Path(__file__).parent / "enrich_award_websites.log"

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
log = logging.getLogger("enrich_award_websites")


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


def extract_contacts(links):
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


def fetch_site(domain):
    for scheme in ("https://", "http://"):
        url = f"{scheme}{domain}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if resp.status_code >= 400:
                continue
            parser = PageParser()
            parser.feed(resp.text[:200_000])
            emails, phones = extract_contacts(parser.links)
            return {
                "fetched_ok": True, "final_url": resp.url,
                "title": parser.title.strip()[:200],
                "meta_description": parser.meta_description[:400],
                "extra_emails": emails, "extra_phones": phones,
            }
        except requests.RequestException:
            continue
    return {"fetched_ok": False}


def domain_from_email(email):
    if not email or "@" not in email:
        return ""
    domain = email.split("@", 1)[1].strip().lower()
    return "" if domain in FREE_EMAIL_DOMAINS else domain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-only", action="store_true")
    args = parser.parse_args()

    source_file = NEW_AWARDS_FILE if args.new_only else AWARDS_FILE
    if not source_file.exists():
        log.info("%s doesn't exist yet — nothing to do", source_file)
        return
    awards = json.loads(source_file.read_text())

    website_by_domain = json.loads(WEBSITE_FILE.read_text()) if WEBSITE_FILE.exists() else {}

    domains = {}
    for a in awards:
        d = domain_from_email(a.get("contact_email", ""))
        if d and d not in website_by_domain:
            domains[d] = True
    domains = sorted(domains.keys())
    log.info("%d award leads (%s), %d new domains to check", len(awards), source_file.name, len(domains))

    for i, domain in enumerate(domains, start=1):
        website_by_domain[domain] = fetch_site(domain)
        if i % 25 == 0:
            WEBSITE_FILE.write_text(json.dumps(website_by_domain, indent=2))
            log.info("Progress: %d/%d", i, len(domains))
        time.sleep(REQUEST_DELAY)

    WEBSITE_FILE.write_text(json.dumps(website_by_domain, indent=2))
    ok = sum(1 for d in domains if website_by_domain[d]["fetched_ok"])
    log.info("Done. %d/%d new domains fetched OK (merged into %s)", ok, len(domains), WEBSITE_FILE)


if __name__ == "__main__":
    main()
