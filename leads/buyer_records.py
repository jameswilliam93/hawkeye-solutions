#!/usr/bin/env python3
"""
Hawkeye Solutions — buyer past-award records (data layer only)

Builds a "who has this buyer awarded similar contracts to before, and how
concentrated is that field" dataset, in the style of Bidvane's "What their
record shows" card. This is a NEW, standalone artifact — it does not touch
the live tender board (pipeline/, tenders/, uk-tenders.json) or the existing
lead-sourcing scripts in leads/ (award_notices.py etc.), though it borrows
their resumable month-chunked-scrape pattern.

Data source: Contracts Finder's OCDS Search API, NOT Find a Tender.
Investigated both before building this — Find a Tender's OCDS API
(api/1.0/ocdsReleasePackages) only has data from ~Feb 2021 onward (nothing
before, confirmed by probing month windows back to 2014 — empty results or
timeouts pre-2021). Contracts Finder's OCDS API
(Published/Notices/OCDS/Search) covers award notices continuously back to
~2014 in the same release shape (classification, award value, supplier
parties), and keeps covering present-day awards too, so it was used as the
single source rather than merging two overlapping feeds and having to
de-dupe FTS notices that are also mirrored on Contracts Finder.

Three resumable phases, each independently re-runnable:

    python3 buyer_records.py fetch              # scrape raw award events
    python3 buyer_records.py resolve             # canonicalise supplier identities
    python3 buyer_records.py build               # aggregate into buyer_records.json
    python3 buyer_records.py preview <buyer> <cpv-prefix>   # sanity-check card, text only

`fetch` needs nothing. `resolve` needs COMPANIES_HOUSE_API_KEY (same env var
the other leads/ scripts use) — it's what turns "GB-CFS-105720" and
"GB-FTS-80946" into the same company when they're the same supplier under
different per-notice IDs. `build` is pure computation over what's already on
disk and can be re-run any time, instantly, as the aggregation logic is
tuned — it never calls either API.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent

# ── Contracts Finder OCDS source ────────────────────────────────────────────

CF_API_BASE   = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
CF_START      = datetime(2014, 1, 1, tzinfo=timezone.utc)  # earliest window with any award releases, probed directly
TIMEOUT       = 90
MAX_PAGES     = 2000
PAGE_DELAY    = 3.5   # Contracts Finder rate-limits harder than Find a Tender in practice —
RETRY_DELAYS  = [60, 120, 300]  # 1.5s/5s (borrowed from award_notices.py, tuned for FTS) tripped
MONTH_DELAY   = 10    # a 429 on almost every month; this pacing avoids that instead of eating the backoff.

RAW_FILE        = HERE / "buyer_records_raw.jsonl"
FETCH_STATE     = HERE / "buyer_records_fetch_state.json"
ENTITIES_FILE   = HERE / "buyer_records_entities.json"
RESOLVE_STATE   = HERE / "buyer_records_resolve_state.json"
OUTPUT_FILE     = HERE / "buyer_records.json"
LOG_FILE        = HERE / "buyer_records.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("buyer_records")

# ── CPV -> sector mapping, copied from pipeline/pipeline.py ────────────────
# Copied rather than imported: pipeline.py is the live tender-board pipeline
# (do-not-touch) and importing it would run its own logging/path setup as a
# side effect. This is a point-in-time snapshot of the same mapping — if the
# live mapping changes meaningfully, re-sync by hand.

CPV_SECTORS = {
    "7995": "Events & Conferences",
    "796": "Recruitment & Staffing",
    "721": "IT Consultancy",
    "722": "IT Consultancy",
    "831": "Management Consultancy",
    "03": "Agriculture & Forestry",
    "09": "Energy",
    "14": "Mining",
    "15": "Food & Beverages",
    "16": "Agricultural Machinery",
    "18": "Clothing & Textiles",
    "22": "Print & Publishing",
    "24": "Chemicals",
    "30": "IT Hardware",
    "31": "Electronics",
    "32": "Communications",
    "33": "Medical Supplies",
    "34": "Vehicles & Transport",
    "35": "Security Equipment",
    "38": "Laboratory Equipment",
    "39": "Furniture",
    "42": "Industrial Machinery",
    "44": "Construction Materials",
    "45": "Construction Works",
    "48": "Software",
    "50": "Maintenance & Repair",
    "51": "Installation Services",
    "55": "Hospitality",
    "60": "Transport Services",
    "63": "Logistics",
    "65": "Utilities",
    "66": "Financial Services",
    "71": "Architecture & Engineering",
    "72": "IT Services",
    "73": "Research & Development",
    "75": "Public Administration",
    "79": "Business Services",
    "83": "Management Consultancy",
    "80": "Education & Training",
    "85": "Health & Social Care",
    "90": "Environmental Services",
    "92": "Recreation & Culture",
    "98": "Other Services",
}


def cpv_to_sector(cpv_code: str) -> str:
    if not cpv_code:
        return "Uncategorised"
    digits = cpv_code.split("-")[0].strip()
    for length in (4, 3, 2):
        if len(digits) >= length and digits[:length] in CPV_SECTORS:
            return CPV_SECTORS[digits[:length]]
    return "Other"


# ── HTTP helpers (same retry/backoff pattern as leads/award_notices.py) ────

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
            try:
                return resp.json()
            except ValueError:
                log.warning("Non-JSON 200 response — treating as failure")
                continue
        if resp.status_code == 429 or resp.status_code >= 500:
            log.warning("%s — will retry", resp.status_code)
            continue
        log.error("Unexpected %s for %s", resp.status_code, url)
        return None
    return None


def month_ranges(start: datetime, end: datetime) -> list[tuple[str, str]]:
    chunks = []
    cur = start
    while cur < end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        chunks.append((cur.strftime("%Y-%m-%dT%H:%M:%SZ"), min(nxt, end).strftime("%Y-%m-%dT%H:%M:%SZ")))
        cur = nxt
    return chunks


def fetch_window(date_from: str, date_to: str) -> list[dict]:
    releases, page = [], 0
    url = CF_API_BASE
    params = {"publishedFrom": date_from, "publishedTo": date_to, "stages": "award", "limit": 100}
    while url and page < MAX_PAGES:
        page += 1
        pkg = fetch_page(url, params if page == 1 else None)
        if not pkg:
            break
        releases.extend(pkg.get("releases", []))
        url = pkg.get("links", {}).get("next", "")
        params = None
        if url:
            time.sleep(PAGE_DELAY)
    return releases


# ── Extraction: one row per (award line, winning supplier) ─────────────────

def extract_award_rows(release: dict) -> list[dict]:
    tags = release.get("tag", [])
    if isinstance(tags, str):
        tags = [tags]
    if not any(t in ("award", "awardUpdate") for t in tags):
        return []

    tender = release.get("tender", {})
    classification = tender.get("classification") or {}
    cpv_code = (classification.get("id") or "").split("-")[0].strip()
    cpv_desc = classification.get("description") or ""
    if not cpv_code:
        # fall back to the first item-level CPV classification, same as the main pipeline
        for item in tender.get("items", []):
            for cls in item.get("additionalClassifications", []):
                if cls.get("scheme") == "CPV" and cls.get("id"):
                    cpv_code = cls["id"].split("-")[0].strip()
                    cpv_desc = cls.get("description", "")
                    break
            if cpv_code:
                break
    if not cpv_code:
        return []  # can't categorise — not usable for a buyer+category record

    parties_by_id = {p["id"]: p for p in release.get("parties", []) if p.get("id")}
    buyer_party = next((p for p in release.get("parties", []) if "buyer" in p.get("roles", [])), {})
    buyer_name = buyer_party.get("name") or release.get("buyer", {}).get("name", "")
    buyer_id = buyer_party.get("id", "")

    rows = []
    for award in release.get("awards", []):
        award_id = award.get("id", "")
        award_date = award.get("date") or release.get("date", "")
        value = award.get("value") or {}
        amount = value.get("amount")
        currency = value.get("currency", "GBP")
        for s in award.get("suppliers", []):
            sid = s.get("id", "")
            party = parties_by_id.get(sid, {})
            supplier_name = party.get("name") or s.get("name", "")
            if not supplier_name:
                continue
            rows.append({
                "ocid": release.get("ocid", ""),
                "release_date": release.get("date", ""),
                "notice_tag": tags[-1] if tags else "",
                "buyer_id": buyer_id,
                "buyer_name": buyer_name,
                "tender_id": tender.get("id", ""),
                "tender_title": tender.get("title", ""),
                "cpv_code": cpv_code,
                "cpv_description": cpv_desc,
                "sector": cpv_to_sector(cpv_code),
                "award_id": award_id,
                "award_date": award_date,
                "value_amount": amount,
                "value_currency": currency,
                "value_stated": amount is not None,
                "supplier_id": sid,
                "supplier_name": supplier_name,
                "source": "contracts_finder",
            })
    return rows


# ── Phase 1: fetch ───────────────────────────────────────────────────────

def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data))


def cmd_fetch(args):
    now = datetime.now(timezone.utc)
    start = CF_START if args.since == "2014" else datetime.strptime(args.since, "%Y-%m").replace(tzinfo=timezone.utc)
    chunks = month_ranges(start, now)

    state = {"done_months": []} if args.fresh else load_json(FETCH_STATE, {"done_months": []})
    if args.fresh and RAW_FILE.exists():
        RAW_FILE.unlink()
    if args.refresh_recent:
        recent_keys = {(now.replace(day=1) - timedelta(days=30 * i)).strftime("%Y-%m") for i in range(args.refresh_recent + 1)}
        state["done_months"] = [m for m in state["done_months"] if m not in recent_keys]
    done = set(state["done_months"])

    todo = [(df, dt) for df, dt in chunks if df[:7] not in done]
    log.info("%d/%d months already done — %d to fetch", len(chunks) - len(todo), len(chunks), len(todo))

    with RAW_FILE.open("a") as out:
        for date_from, date_to in todo:
            key = date_from[:7]
            log.info("Fetching %s..%s", date_from, date_to)
            releases = fetch_window(date_from, date_to)
            rows_this_month = 0
            for release in releases:
                for row in extract_award_rows(release):
                    out.write(json.dumps(row) + "\n")
                    rows_this_month += 1
            out.flush()
            state["done_months"].append(key)
            save_json(FETCH_STATE, state)
            log.info("  %s: %d releases scanned, %d award-supplier rows written", key, len(releases), rows_this_month)
            time.sleep(MONTH_DELAY)

    log.info("Fetch complete. Raw rows in %s", RAW_FILE)


# ── Phase 2: resolve supplier identity ──────────────────────────────────────

LEGAL_SUFFIXES = re.compile(
    r"\b(limited|ltd|llp|plc|cic|llc|incorporated|inc|the|and|co|company|group|holdings?)\b",
    re.IGNORECASE,
)
PUNCT = re.compile(r"[^\w\s]")


def normalize_name(name: str) -> str:
    n = name.lower()
    n = PUNCT.sub(" ", n)
    n = LEGAL_SUFFIXES.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def normalize_coh_number(raw_id: str) -> str | None:
    """GB-COH-01644241 / GB-COH-1644241 -> 01644241 (Companies House numbers are
    8 chars, left-padded with zeros for numeric-only registrations; Scottish/NI
    prefixes like SC/NI/OC are already the right length and left as-is)."""
    if not raw_id or not raw_id.upper().startswith("GB-COH-"):
        return None
    num = raw_id.split("-", 2)[2].strip().upper()
    if num.isdigit():
        return num.zfill(8)
    return num


CH_API_BASE   = "https://api.company-information.service.gov.uk"
CH_TIMEOUT    = 30
CH_RETRY      = [10, 30, 90, 300]
CH_DELAY      = 0.52  # CH's real limit is 600 req/5min = 1 req every 0.5s — companies_house.py's
                      # 0.15s constant (copied from there originally) is 3x too fast for sustained
                      # volume and was triggering chronic 429s with expensive backoff on this scale.

# Copied from leads/companies_house.py — same free, automatable size proxy.
SIZE_BAND = {
    "micro-entity": "micro", "small": "small", "medium": "medium", "group": "large",
    "dormant": "dormant", "audited-abridged": "small", "unaudited-abridged": "small",
    "full": "unknown-full", "total-exemption-full": "unknown-full", "no-accounts-filed": "unknown",
}
SME_BANDS = {"micro", "small", "medium"}


def ch_request(session, url, params=None):
    for attempt, delay in enumerate([0] + CH_RETRY, start=1):
        if delay:
            log.warning("CH retry %d — waiting %ds", attempt - 1, delay)
            time.sleep(delay)
        try:
            resp = session.get(url, params=params, timeout=CH_TIMEOUT)
        except requests.RequestException as e:
            log.warning("CH request failed: %s", e)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        if resp.status_code in (429, 500, 502, 503, 504):
            log.warning("CH %s — will retry", resp.status_code)
            continue
        log.error("CH unexpected %s for %s", resp.status_code, url)
        return None
    return None


def ch_search_best_match(session, name: str, target_norm: str) -> dict | None:
    data = ch_request(session, f"{CH_API_BASE}/search/companies", params={"q": name, "items_per_page": 5})
    if not data:
        return None
    for item in data.get("items", []):
        if normalize_name(item.get("title", "")) == target_norm:
            return {"company_number": item.get("company_number"), "method": "coh_search_exact"}
    items = data.get("items", [])
    if items and normalize_name(items[0].get("title", "")) :
        # no exact normalised match — top hit kept only as a lower-confidence fallback
        return {"company_number": items[0].get("company_number"), "method": "coh_search_fuzzy"}
    return None


def ch_fetch_size(session, company_number: str) -> tuple[str, str]:
    profile = ch_request(session, f"{CH_API_BASE}/company/{company_number}")
    if not profile:
        return "unknown", ""
    accounts_type = (profile.get("accounts", {}) or {}).get("last_accounts", {}).get("type")
    return SIZE_BAND.get(accounts_type, "unknown"), profile.get("company_name", "")


def cmd_resolve(args):
    import os
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    session = None
    if key:
        session = requests.Session()
        session.auth = (key, "")
    else:
        log.warning(
            "COMPANIES_HOUSE_API_KEY not set — proceeding in degraded mode: suppliers that already "
            "carry a GB-COH-* id in the raw data still resolve correctly (no API needed for that), "
            "but SME/size tagging is skipped and ambiguous names without a COH id fall back to "
            "normalised-name matching instead of a Companies House search. Export the key and "
            "re-run `resolve` (no --fresh needed) to upgrade those entries later."
        )

    if not RAW_FILE.exists():
        log.error("%s doesn't exist yet — run `fetch` first.", RAW_FILE)
        sys.exit(1)

    # Collect every distinct raw supplier identity seen.
    raw_ids: dict[str, set[str]] = defaultdict(set)   # norm_name -> {raw names}
    coh_ids: dict[str, str] = {}                       # norm_name -> coh number, straight off the data
    with RAW_FILE.open() as f:
        for line in f:
            row = json.loads(line)
            name = row["supplier_name"]
            norm = normalize_name(name)
            if not norm:
                continue
            raw_ids[norm].add(name)
            coh = normalize_coh_number(row.get("supplier_id", ""))
            if coh:
                coh_ids.setdefault(norm, coh)

    entities = {} if args.fresh else load_json(ENTITIES_FILE, {}).get("suppliers", {})
    state = {"done": []} if args.fresh else load_json(RESOLVE_STATE, {"done": []})
    done = set(state["done"])

    todo = [n for n in raw_ids if n not in done]
    log.info("%d distinct supplier names, %d already resolved, %d to resolve (%d already have a Companies House number in the raw data)",
              len(raw_ids), len(done), len(todo), len(coh_ids))

    size_cache: dict[str, tuple[str, str]] = {}
    # Re-saving the whole entities dict every 25 items is fine at hundreds of
    # suppliers but rewrites a many-MB file thousands of times at six figures
    # of distinct names — scale the checkpoint interval with the job size so
    # resumability doesn't come at the cost of quadratic disk I/O.
    checkpoint_every = max(25, len(todo) // 200)

    for i, norm in enumerate(todo, start=1):
        display_name = sorted(raw_ids[norm], key=len, reverse=True)[0]  # longest spelling, usually most complete
        if norm in coh_ids:
            coh = coh_ids[norm]
            method, confidence = "raw_coh_id", 1.0
        elif session:
            best = ch_search_best_match(session, display_name, norm)
            time.sleep(CH_DELAY)
            if best and best.get("company_number"):
                coh = best["company_number"]
                method = best["method"]
                confidence = 0.95 if method == "coh_search_exact" else 0.6
            else:
                coh, method, confidence = None, "name_only", 0.3
        else:
            coh, method, confidence = None, "name_only_no_key", 0.3

        if coh and session:
            if coh not in size_cache:
                size_cache[coh] = ch_fetch_size(session, coh)
                time.sleep(CH_DELAY)
            size_band, ch_name = size_cache[coh]
            canonical_id = f"GB-COH-{coh}"
            canonical_name = ch_name or display_name
        elif coh:
            size_band, canonical_id, canonical_name = "unknown", f"GB-COH-{coh}", display_name
        else:
            size_band, canonical_id, canonical_name = "unknown", f"name:{norm}", display_name

        entities[norm] = {
            "canonical_id": canonical_id,
            "canonical_name": canonical_name,
            "match_method": method,
            "match_confidence": confidence,
            "size_band": size_band,
            "is_sme": (size_band in SME_BANDS) if size_band != "unknown" else None,
        }
        state["done"].append(norm)
        if i % checkpoint_every == 0:
            save_json(ENTITIES_FILE, {"suppliers": entities})
            save_json(RESOLVE_STATE, state)
            log.info("Progress: %d/%d", i, len(todo))

    save_json(ENTITIES_FILE, {"suppliers": entities})
    save_json(RESOLVE_STATE, state)
    log.info("Resolve complete. %d supplier identities in %s", len(entities), ENTITIES_FILE)


# ── Phase 3: build / aggregate ───────────────────────────────────────────────

MIN_AWARDS_FOR_CATEGORY = 5
CPV_DEPTHS = (8, 6, 4, 2)
ALL_CATEGORIES = "*"  # category_cpv_prefix marker for a buyer-wide record

# Cut-down copy of the build output that IS committed, so the daily GitHub
# Action's page generator can see it (the full buyer_records.json is 80MB+ and
# gitignored). Only what the card renders: top N suppliers, the rest folded
# into one "others" summary.
SLIM_FILE = HERE.parent / "pipeline" / "buyer_records_slim.json.gz"
SLIM_TOP_SUPPLIERS = 10
SLIM_SUPPLIER_FIELDS = ("display_name", "wins", "valued_wins", "is_sme", "share_of_value", "typical_value")
SLIM_RECORD_FIELDS = (
    "buyer_key", "buyer_name", "category_cpv_prefix", "category_cpv_depth", "category_label",
    "sector", "total_awards", "total_suppliers", "total_value_amount", "valued_awards",
    "value_min", "value_mid", "value_max", "earliest_award_date", "new_suppliers_last_12m",
)


def export_slim(records: list[dict]) -> None:
    slim = []
    for r in records:
        if r["total_suppliers"] < 2:
            continue  # the card never renders these
        s = {k: r[k] for k in SLIM_RECORD_FIELDS}
        top = r["suppliers"][:SLIM_TOP_SUPPLIERS]
        rest = r["suppliers"][SLIM_TOP_SUPPLIERS:]
        s["suppliers"] = [{k: sup[k] for k in SLIM_SUPPLIER_FIELDS} for sup in top]
        if rest:
            s["others"] = {
                "count": len(rest),
                "wins": sum(x["wins"] for x in rest),
                "share_of_value": round(sum(x["share_of_value"] or 0 for x in rest), 4)
                                  if any(x["valued_wins"] for x in rest) else None,
            }
        slim.append(s)
    payload = json.dumps(slim, separators=(",", ":")).encode()
    # mtime=0 keeps the bytes identical across rebuilds of unchanged data, so
    # git doesn't see a "change" every time build is re-run.
    SLIM_FILE.write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    log.info("Slim export: %d records -> %s (%.1f MB)", len(slim), SLIM_FILE, SLIM_FILE.stat().st_size / 1e6)


def normalize_buyer_key(name: str) -> str:
    return normalize_name(name)


def parse_dt(s: str) -> datetime:
    """Contracts Finder mixes 'Z' and explicit '+01:00'-style offsets across
    releases — comparing those as raw strings doesn't reliably sort them in
    real chronological order, so every date comparison below parses first."""
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_raw_rows() -> list[dict]:
    if not RAW_FILE.exists():
        return []
    rows = []
    with RAW_FILE.open() as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """Same (ocid, award_id, supplier_id) can appear more than once — an
    'award' notice later gets a republished 'awardUpdate', or a month window
    gets re-fetched. Keep only the most recently published version of each
    specific award-to-supplier fact."""
    latest: dict[tuple, dict] = {}
    for row in rows:
        key = (row["ocid"], row["award_id"], row["supplier_id"])
        existing = latest.get(key)
        if not existing or parse_dt(row["release_date"]) > parse_dt(existing["release_date"]):
            latest[key] = row
    return list(latest.values())


# Free-text the buyer typed into the supplier field instead of a real winner
# ("N/A", "Various", "Not awarded", "Please see attachment", "test supplier
# only"). Left in, these show up on the card ranked as if they were firms.
_PLACEHOLDER_SUPPLIER = re.compile(
    r"please|\bsee\b|various|multiple supplier|several supplier|list of|not (yet )?(known|awarded|applicable)"
    r"|^\W*$|^n/?a$|^tb[cd]\b|^none$|^unknown|^test\b|^suppliers?$|^\d+ suppliers",
    re.IGNORECASE,
)
_REAL_COMPANY_SUFFIX = re.compile(r"\b(ltd|limited|plc|llp|lp|inc|cic|llc)\.?\s*$", re.IGNORECASE)


def is_placeholder_supplier(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True
    # A registered-company suffix means it's a real firm, even if its name
    # happens to trip a pattern (e.g. "Testing Circle Ltd").
    return bool(_PLACEHOLDER_SUPPLIER.search(n)) and not _REAL_COMPANY_SUFFIX.search(n)


def pick_cpv_group(buyer_rows: list[dict]) -> dict[str, list[dict]]:
    """For one buyer's rows, cluster by CPV prefix at the finest depth that
    still gives each group >= MIN_AWARDS_FOR_CATEGORY awards (counting each
    award once even if it has multiple suppliers), rolling up to a broader
    prefix otherwise. Returns {cpv_prefix: [rows in that group]}."""
    by_award: dict[str, list[dict]] = defaultdict(list)
    for r in buyer_rows:
        by_award[(r["ocid"], r["award_id"])].append(r)

    assigned: dict[str, list[dict]] = {}
    remaining_award_keys = set(by_award.keys())

    for depth in CPV_DEPTHS:
        groups: dict[str, list] = defaultdict(list)
        for ak in remaining_award_keys:
            cpv = by_award[ak][0]["cpv_code"]
            prefix = cpv[:depth] if len(cpv) >= depth else cpv
            groups[prefix].append(ak)
        for prefix, award_keys in groups.items():
            if len(award_keys) >= MIN_AWARDS_FOR_CATEGORY or depth == CPV_DEPTHS[-1]:
                rows_here = [r for ak in award_keys for r in by_award[ak]]
                assigned[prefix] = assigned.get(prefix, []) + rows_here
                remaining_award_keys -= set(award_keys)

    return assigned


# UK procurement notices routinely use £0 or £1 as a placeholder when the
# buyer didn't want to (or couldn't) disclose a real value, rather than
# leaving the field empty — the Bidvane example calls this out explicitly
# ("this notice does not state a value"). Treated as unstated here so a
# handful of placeholder rows don't drag the min/typical-value figures down
# to near-zero.
MIN_SENSIBLE_VALUE = 100
# Above this a single award's stated value is overwhelmingly a framework
# ceiling or a data-entry error (real examples: £120bn from a borough council,
# £72bn single-supplier CCS frameworks) — treat it as undisclosed rather than
# let it dominate every share and value figure.
MAX_SENSIBLE_VALUE = 1_000_000_000


def sensible_value(amount):
    return amount if amount is not None and MIN_SENSIBLE_VALUE <= amount < MAX_SENSIBLE_VALUE else None


# Free-text buyer-entered award dates occasionally contain outright garbage —
# real examples pulled from this dataset include "1898" and "2108". A release
# can't have been published outside Contracts Finder's own operating window,
# so release_date is always trustworthy; award_date is only trusted when it
# falls in a plausible range, else we fall back to release_date instead.
DATE_FLOOR = datetime(2000, 1, 1, tzinfo=timezone.utc)


def sensible_date(award_date: str, release_date: str, now: datetime) -> str:
    candidate = award_date or release_date
    parsed = parse_dt(candidate)
    if DATE_FLOOR <= parsed <= now + timedelta(days=1):
        return candidate
    return release_date


def resolve_supplier(entities: dict, row: dict) -> tuple[str, str, str | None, bool | None]:
    norm = normalize_name(row["supplier_name"])
    ent = entities.get(norm)
    if not ent:
        return f"name:{norm}", row["supplier_name"], "unknown", None
    return ent["canonical_id"], ent["canonical_name"], ent["size_band"], ent["is_sme"]


def build_record(buyer_name: str, buyer_key: str, cpv_prefix: str, rows: list[dict], entities: dict, now: datetime) -> dict:
    by_award: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_award[(r["ocid"], r["award_id"])].append(r)

    supplier_stats: dict[str, dict] = {}
    total_value = 0.0
    valued_awards = 0
    values = []
    cutoff = (now - timedelta(days=365)).isoformat()
    first_seen_before_cutoff: set[str] = set()
    suppliers_in_last_12m: set[str] = set()
    cpv_desc_counts: dict[str, int] = defaultdict(int)
    sector_counts: dict[str, int] = defaultdict(int)

    # A notice naming several winners is almost always a framework/DPS, and its
    # stated value is the ceiling for the WHOLE arrangement, repeated against
    # every supplier — not money any one of them was paid. Crediting each
    # supplier with it produced shares over 100% (e.g. ten firms each "winning"
    # a £37bn NHS framework). Such awards still count as wins, but their value
    # is treated as not attributable.
    suppliers_per_notice: dict[str, set] = defaultdict(set)
    for r in rows:
        suppliers_per_notice[r["ocid"]].add(normalize_name(r["supplier_name"]))

    for (ocid, award_id), award_rows in by_award.items():
        value = sensible_value(award_rows[0]["value_amount"])
        if len(suppliers_per_notice[ocid]) > 1:
            value = None
        date = sensible_date(award_rows[0]["award_date"], award_rows[0]["release_date"], now)
        cpv_desc_counts[award_rows[0]["cpv_description"]] += 1
        sector_counts[award_rows[0]["sector"]] += 1
        if value is not None:
            values.append(value)
            total_value += value
            valued_awards += 1
        supplier_ids_this_award = set()
        for r in award_rows:
            cid, cname, size_band, is_sme = resolve_supplier(entities, r)
            if cid in supplier_ids_this_award:
                continue  # same firm listed twice on one award — count it once
            supplier_ids_this_award.add(cid)
            s = supplier_stats.setdefault(cid, {
                "canonical_id": cid, "display_name": cname, "wins": 0,
                "total_value": 0.0, "valued_wins": 0, "size_band": size_band,
                "is_sme": is_sme, "first_award_date": date, "last_award_date": date,
            })
            s["wins"] += 1
            if value is not None:
                s["total_value"] += value
                s["valued_wins"] += 1
            if parse_dt(date) < parse_dt(s["first_award_date"]):
                s["first_award_date"] = date
            if parse_dt(date) > parse_dt(s["last_award_date"]):
                s["last_award_date"] = date
        if parse_dt(date) < parse_dt(cutoff):
            first_seen_before_cutoff |= supplier_ids_this_award
        else:
            suppliers_in_last_12m |= supplier_ids_this_award

    new_suppliers_last_12m = suppliers_in_last_12m - first_seen_before_cutoff
    # a supplier counts as "new" only if every one of their wins falls inside the window
    new_suppliers_last_12m = {
        sid for sid in new_suppliers_last_12m
        if parse_dt(supplier_stats[sid]["first_award_date"]) >= parse_dt(cutoff)
    }

    total_awards = len(by_award)
    suppliers_sorted = sorted(supplier_stats.values(), key=lambda s: -s["total_value"])
    for s in suppliers_sorted:
        s["share_of_value"] = round(s["total_value"] / total_value, 4) if total_value else None
        s["share_of_count"] = round(s["wins"] / total_awards, 4) if total_awards else None
        s["typical_value"] = round(s["total_value"] / s["valued_wins"], 2) if s["valued_wins"] else None

    sector = max(sector_counts, key=sector_counts.get) if sector_counts else ""
    # Only name a specific type of work when the group really is that specific
    # (6-8 digit CPV prefix). A 2-4 digit rollup mixes many kinds of work, so
    # naming its single most common description would overclaim — use the
    # broad sector for the prefix instead. Buyer-wide records get no label.
    if cpv_prefix == ALL_CATEGORIES:
        cpv_description = ""
    elif len(cpv_prefix) >= 6:
        cpv_description = max(cpv_desc_counts, key=cpv_desc_counts.get) if cpv_desc_counts else ""
    else:
        broad = cpv_to_sector(cpv_prefix)
        cpv_description = "" if broad in ("Other", "Uncategorised") else broad

    return {
        "buyer_key": buyer_key,
        "buyer_name": buyer_name,
        "category_cpv_prefix": cpv_prefix,
        "category_cpv_depth": 0 if cpv_prefix == ALL_CATEGORIES else len(cpv_prefix),
        "category_label": cpv_description,
        "sector": sector,
        "total_awards": total_awards,
        "total_suppliers": len(supplier_stats),
        "total_value_amount": round(total_value, 2) if valued_awards else None,
        "valued_awards": valued_awards,
        "value_min": min(values) if values else None,
        "value_mid": sorted(values)[len(values) // 2] if values else None,
        "value_max": max(values) if values else None,
        "earliest_award_date": min((sensible_date(r["award_date"], r["release_date"], now) for r in rows), key=parse_dt),
        "latest_award_date": max((sensible_date(r["award_date"], r["release_date"], now) for r in rows), key=parse_dt),
        "new_suppliers_last_12m": sorted(
            supplier_stats[sid]["display_name"] for sid in new_suppliers_last_12m
        ),
        "suppliers": suppliers_sorted,
    }


def cmd_build(args):
    rows = load_raw_rows()
    if not rows:
        log.error("No raw rows found — run `fetch` first.")
        sys.exit(1)
    rows = dedupe_rows(rows)
    before = len(rows)
    rows = [r for r in rows if not is_placeholder_supplier(r["supplier_name"])]
    log.info("%d deduped award-supplier rows loaded (%d placeholder 'suppliers' dropped)", len(rows), before - len(rows))

    entities = load_json(ENTITIES_FILE, {}).get("suppliers", {})
    if not entities:
        log.warning("No entity resolution map found (run `resolve` for proper name matching) — "
                     "falling back to normalised-name-only grouping for all suppliers.")

    by_buyer: dict[str, list[dict]] = defaultdict(list)
    buyer_display: dict[str, str] = {}
    for r in rows:
        key = normalize_buyer_key(r["buyer_name"])
        if not key:
            continue
        by_buyer[key].append(r)
        buyer_display.setdefault(key, r["buyer_name"])

    now = datetime.now(timezone.utc).isoformat()
    records = []
    candidate_groups = 0
    buyer_wide = 0
    for buyer_key, buyer_rows in by_buyer.items():
        groups = pick_cpv_group(buyer_rows)
        candidate_groups += len(groups)
        for cpv_prefix, group_rows in groups.items():
            if len({(r["ocid"], r["award_id"]) for r in group_rows}) < MIN_AWARDS_FOR_CATEGORY:
                continue  # still too thin even at the broadest rollup — not worth showing
            records.append(build_record(buyer_display[buyer_key], buyer_key, cpv_prefix, group_rows, entities, datetime.now(timezone.utc)))
        # Buyer-wide fallback across every category — used when a tender has no
        # CPV code, or this buyer has too little history in the tender's own
        # category. Never a guess: it's labelled as "all their contracts".
        if len({(r["ocid"], r["award_id"]) for r in buyer_rows}) >= MIN_AWARDS_FOR_CATEGORY:
            records.append(build_record(buyer_display[buyer_key], buyer_key, ALL_CATEGORIES, buyer_rows, entities, datetime.now(timezone.utc)))
            buyer_wide += 1

    save_json(OUTPUT_FILE, records)
    export_slim(records)
    log.info("%d of those are buyer-wide (all-category) records", buyer_wide)
    log.info("Build complete. %d buyer+category records (>= %d awards each) written to %s",
              len(records), MIN_AWARDS_FOR_CATEGORY, OUTPUT_FILE)
    log.info("%d buyer+category combinations seen at all; %d of them (%.0f%%) cleared the %d-award bar",
              candidate_groups, len(records),
              100 * len(records) / candidate_groups if candidate_groups else 0,
              MIN_AWARDS_FOR_CATEGORY)


# ── Debug preview — NOT the deliverable, just a sanity check ───────────────

def fmt_money(amount) -> str:
    if amount is None:
        return "n/a"
    if amount >= 1_000_000:
        return f"£{amount/1_000_000:.1f}m"
    if amount >= 1_000:
        return f"£{amount/1_000:.0f}k"
    return f"£{amount:.0f}"


def cmd_preview(args):
    records = load_json(OUTPUT_FILE, [])
    matches = [
        r for r in records
        if args.buyer.lower() in r["buyer_name"].lower()
        and (not args.cpv or r["category_cpv_prefix"].startswith(args.cpv))
    ]
    if not matches:
        print("No matching buyer+category record found.")
        return
    for r in matches[: args.limit]:
        print(f"\n=== {r['buyer_name']} — {r['category_label'] or r['sector']} ===")
        top3_share = sum(s["share_of_value"] or 0 for s in r["suppliers"][:3])
        print(f"What their record shows")
        print(f"  Dominated by a handful — {top3_share*100:.0f}% of their {r['category_label'] or r['sector']} "
              f"contracts went to the top three, of {r['total_suppliers']} suppliers who have won")
        print(f"  Value range: {fmt_money(r['value_min'])} (lowest), {fmt_money(r['value_mid'])} (middle), "
              f"{fmt_money(r['value_max'])} (highest)")
        print(f"  They have awarded {r['total_awards']} {r['category_label'] or r['sector']} contracts "
              f"since {r['earliest_award_date'][:4]}.")
        print(f"\nWho wins the money")
        for s in r["suppliers"]:
            sme_tag = " (SME)" if s["is_sme"] else ""
            share = f"{(s['share_of_value'] or 0)*100:.0f}%"
            print(f"  - {s['display_name']}{sme_tag} — {share}, {s['wins']} win(s), typically {fmt_money(s['typical_value'])}")
        print(f"\nWhat's changed lately")
        if r["new_suppliers_last_12m"]:
            print(f"  New in the last 12 months: {', '.join(r['new_suppliers_last_12m'])}")
        else:
            print(f"  No new supplier in the last 12 months — all {r['total_suppliers']} firms winning here had won before")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="scrape raw award events from Contracts Finder")
    p_fetch.add_argument("--since", default="2014", help="YYYY-MM to start from, or '2014' for the full depth probed (default)")
    p_fetch.add_argument("--fresh", action="store_true")
    p_fetch.add_argument("--refresh-recent", type=int, default=2)
    p_fetch.set_defaults(func=cmd_fetch)

    p_resolve = sub.add_parser("resolve", help="canonicalise supplier identities via Companies House")
    p_resolve.add_argument("--fresh", action="store_true")
    p_resolve.set_defaults(func=cmd_resolve)

    p_build = sub.add_parser("build", help="aggregate raw rows + entity map into buyer_records.json")
    p_build.set_defaults(func=cmd_build)

    p_preview = sub.add_parser("preview", help="print a text-only sanity-check card (debug only, not the deliverable)")
    p_preview.add_argument("buyer", help="substring of buyer name")
    p_preview.add_argument("cpv", nargs="?", default="", help="CPV prefix filter, optional")
    p_preview.add_argument("--limit", type=int, default=3)
    p_preview.set_defaults(func=cmd_preview)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
