#!/usr/bin/env python3
"""
Hawkeye Solutions — IndexNow submitter

Reads indexnow_urls.txt (written by generate_pages.py: today's new/changed
tender URLs plus all 19 hub pages) and pushes them to the IndexNow API, which
fans out to every participating search engine (Bing, Yandex, Seznam, Naver,
and others — not Google, which doesn't take part in IndexNow).

Deliberately never raises or exits non-zero: a failure here (network blip,
API hiccup) must never fail the daily workflow or block the tender data
commit, which is the actual critical step. Worst case, today's URLs simply
don't get an instant ping and get picked up on Bing's/etc. own crawl schedule
instead — no functional loss, just a slower discovery path.

Usage:
    python3 submit_indexnow.py
    python3 submit_indexnow.py --urls-file /path/to/indexnow_urls.txt
"""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

HOST            = "hawkeye-solutions.co.uk"
INDEXNOW_KEY    = "30cdb6dcf5933678ab5c60fdd8571466"
KEY_LOCATION    = f"https://{HOST}/{INDEXNOW_KEY}.txt"
ENDPOINT        = "https://api.indexnow.org/indexnow"
URLS_FILE       = Path("indexnow_urls.txt")
MAX_PER_REQUEST = 10_000  # IndexNow's documented per-request cap


def submit(urls: list[str]) -> None:
    if not urls:
        print("IndexNow: nothing to submit this run.")
        return

    payload = json.dumps({
        "host": HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls[:MAX_PER_REQUEST],
    }).encode("utf-8")

    req = urllib.request.Request(
        ENDPOINT, data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            print(f"IndexNow: submitted {len(urls)} URL(s) — HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        # IndexNow returns 200/202 on success; 4xx usually means the key
        # file isn't reachable yet (e.g. this is the very first run before
        # Netlify has deployed it) — log and move on, never fail the job.
        print(f"IndexNow: submission returned HTTP {e.code} — {e.read()[:300]}")
    except Exception as e:
        print(f"IndexNow: submission failed ({e}) — continuing, non-fatal.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls-file", default=str(URLS_FILE))
    args = parser.parse_args()

    path = Path(args.urls_file)
    if not path.exists():
        print(f"IndexNow: {path} not found, skipping (run generate_pages.py first).")
        return

    urls = [u.strip() for u in path.read_text(encoding="utf-8").splitlines() if u.strip()]
    submit(urls)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Belt and suspenders: this script must never be the reason the
        # daily workflow goes red.
        print(f"IndexNow: unexpected error ({e}) — non-fatal, continuing.")
