#!/usr/bin/env python3
"""
Hawkeye Solutions — guess + verify a website for Tier 2 leads

Companies House doesn't publish a website, so for every Tier 2 lead this
generates a handful of plausible domains from the company name (legal
suffix stripped, squashed and hyphenated, across .co.uk/.com), checks
which one actually resolves to a real page, and sanity-checks the page
text actually mentions a significant word from the company name before
trusting the match — guards against a guessed domain happening to
resolve to someone else's unrelated site.

Once a domain is confirmed, pulls the same specialism blurb and bonus
contact details as enrich_websites.py does for Tier 1 (duplicated here
deliberately rather than imported, so importing this module doesn't
reconfigure enrich_websites.py's own logging as a side effect).

Won't catch every company — only works when the domain closely follows
the legal name — but should unlock a real chunk of the 1,756 Tier 2
leads that currently have no contact info beyond a director's name.

Usage:
    python3 guess_domains.py           # resumes if interrupted
    python3 guess_domains.py --fresh    # ignore saved progress
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

SCORED_FILE = Path(__file__).parent / "scored_leads.json"
OUTPUT_FILE = Path(__file__).parent / "domain_guesses.json"
STATE_FILE  = Path(__file__).parent / "guess_domains_state.json"
LOG_FILE    = Path(__file__).parent / "guess_domains.log"

TIMEOUT = 6
REQUEST_DELAY = 0.1
TLDS = [".co.uk", ".com"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; HawkeyeLeadResearch/1.0)"}
LEGAL_SUFFIXES = re.compile(r"\b(limited|ltd|llp|plc|llc)\b\.?", re.I)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("guess_domains")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.links = []
        self.body_text = ""
        self._in_title = False
        self._skip = False  # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style"):
            self._skip = True
        elif tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            if name in ("description", "og:description") and not self.meta_description:
                self.meta_description = (attrs.get("content") or "").strip()
        elif tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip and len(self.body_text) < 3000:
            self.body_text += " " + data


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
                "body_text": parser.body_text[:3000],
                "extra_emails": emails, "extra_phones": phones,
            }
        except requests.RequestException:
            continue
    return {"fetched_ok": False}


def slugs_for(company_name):
    name = LEGAL_SUFFIXES.sub("", company_name)
    words = re.findall(r"[a-z0-9]+", name.lower())
    if not words:
        return []
    bases = list(dict.fromkeys(["".join(words), "-".join(words)]))
    return [base + tld for base in bases for tld in TLDS], words


def looks_like_match(site, words):
    """Require every distinctive word in the company name to appear on the
    page — a single generic word matching (e.g. "plus") isn't enough and
    was producing real false positives (Kare Plus -> an unrelated betting
    site) before this was tightened."""
    text = f"{site.get('title','')} {site.get('meta_description','')} {site.get('body_text','')}".lower()
    significant = [w for w in words if len(w) > 3]
    if not significant:
        return False
    return all(w in text for w in significant)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    leads = json.loads(SCORED_FILE.read_text())
    tier2 = [l for l in leads if l["tier"] == 2 and not l.get("website")]
    log.info("%d Tier 2 leads without a website to try", len(tier2))

    state = {} if args.fresh else load_state()

    for i, lead in enumerate(tier2, start=1):
        number = lead["company_number"]
        if number in state:
            continue
        candidates, words = slugs_for(lead["company_name"])
        found = None
        for domain in candidates:
            site = fetch_site(domain)
            if site["fetched_ok"] and looks_like_match(site, words):
                found = {"domain": domain, **site}
                break
            time.sleep(REQUEST_DELAY)
        state[number] = found or {"domain": None, "fetched_ok": False}
        if i % 50 == 0:
            STATE_FILE.write_text(json.dumps(state))
            matched_so_far = sum(1 for v in state.values() if v.get("fetched_ok"))
            log.info("Progress: %d/%d (%d matched)", i, len(tier2), matched_so_far)

    STATE_FILE.write_text(json.dumps(state))
    OUTPUT_FILE.write_text(json.dumps(state, indent=2))
    matched = sum(1 for v in state.values() if v.get("fetched_ok"))
    log.info("Done. %d/%d Tier 2 leads matched to a real website", matched, len(state))


if __name__ == "__main__":
    main()
