#!/usr/bin/env python3
"""
Hawkeye Solutions — Search Console sitemap resubmission

Authenticates via Application Default Credentials, set up by the
google-github-actions/auth step in the workflow using Workload Identity
Federation — no downloadable service account key involved (the hosting
Google Cloud project has key creation disabled by org policy, so WIF is
the only viable path, not just the nicer one).

Looks up the verified property via sites.list rather than hardcoding
whether it's a Domain or URL-prefix property, then PUTs sitemap.xml to
the sitemaps.submit endpoint.

Deliberately never raises or exits non-zero: mirrors submit_indexnow.py's
philosophy — this must never block the daily tender pipeline's commit/push,
which is the actual critical step. Worst case, this run's sitemap update
is picked up by Google's own periodic re-crawl instead of an instant nudge.
"""

import urllib.parse

import requests

SITEMAP_URL = "https://hawkeye-solutions.co.uk/sitemap.xml"
SITE_MATCH = "hawkeye-solutions.co.uk"
SCOPES = ["https://www.googleapis.com/auth/webmasters"]


def main():
    try:
        import google.auth
        import google.auth.transport.requests
    except ImportError as e:
        print(f"Search Console: google-auth not installed ({e}) — non-fatal, continuing.")
        return

    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        creds.refresh(google.auth.transport.requests.Request())
    except Exception as e:
        print(f"Search Console: auth failed ({e}) — non-fatal, continuing.")
        return

    headers = {"Authorization": f"Bearer {creds.token}"}

    try:
        r = requests.get("https://www.googleapis.com/webmasters/v3/sites", headers=headers, timeout=20)
        r.raise_for_status()
        sites = [s["siteUrl"] for s in r.json().get("siteEntry", [])]
    except Exception as e:
        print(f"Search Console: could not list verified properties ({e}) — non-fatal, continuing.")
        return

    site_url = next((s for s in sites if SITE_MATCH in s), None)
    if not site_url:
        print(f"Search Console: no verified property matching {SITE_MATCH!r} found "
              f"(service account can see: {sites or 'none'}) — check it was granted "
              f"Full access in Search Console's Users and permissions. Non-fatal, continuing.")
        return

    submit_url = (
        "https://www.googleapis.com/webmasters/v3/sites/"
        f"{urllib.parse.quote(site_url, safe='')}/sitemaps/"
        f"{urllib.parse.quote(SITEMAP_URL, safe='')}"
    )

    try:
        r = requests.put(submit_url, headers=headers, timeout=20)
        if r.status_code in (200, 204):
            print(f"Search Console: sitemap resubmitted successfully for {site_url}")
        else:
            print(f"Search Console: submit returned HTTP {r.status_code} — {r.text[:300]}")
    except Exception as e:
        print(f"Search Console: submit failed ({e}) — non-fatal, continuing.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Search Console: unexpected error ({e}) — non-fatal, continuing.")
