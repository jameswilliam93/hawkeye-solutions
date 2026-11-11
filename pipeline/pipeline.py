#!/usr/bin/env python3
"""
Hawkeye Solutions — UK Tender Data Pipeline

Daily cron (run at 6am):
    0 6 * * * cd /Users/jamespitt/hawkeye-tender-pipeline && python3.14 pipeline.py

One-time full backfill (resumable if interrupted):
    python3.14 pipeline.py --backfill
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Configuration ──────────────────────────────────────────────────────────────

OUTPUT_FILE    = Path("uk-tenders.json")
STATE_FILE     = Path("pipeline_state.json")
PROGRESS_FILE  = Path("backfill_progress.json")
LOG_FILE       = Path("pipeline.log")

API_BASE       = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"

TIMEOUT        = 90       # seconds per request
MAX_PAGES      = 500      # safety cap per date window
PAGE_DELAY     = 1.5      # polite pause between pages (seconds)
RETRY_DELAYS   = [60, 120, 300]  # backoff on 429 rate-limit (seconds)
MONTH_DELAY    = 5        # pause between months (seconds)
EXPIRE_DAYS    = 0        # only keep tenders with a future deadline (or no deadline)
HISTORY_DAYS   = 365     # also drop tenders published more than this many days ago (keeps file small)

BACKFILL_START = datetime(2022, 1, 1, tzinfo=timezone.utc)  # Jan 2022 — captures 4-year framework agreements and DPS

OPEN_TAGS = {"tender", "tenderAmendment", "tenderUpdate"}

# Fields preserved from existing record when a partial tenderUpdate has no value for them
PRESERVE_ON_UPDATE = (
    "deadline", "url", "value", "currency", "region", "sector",
    "cpvCode", "cpvCodes", "buyerContact", "buyerAddress", "lots", "documents",
)

# NUTS/ITL region codes → readable UK region names
NUTS_REGIONS = {
    "UKC": "North East England",   "UKD": "North West England",
    "UKE": "Yorkshire and The Humber", "UKF": "East Midlands",
    "UKG": "West Midlands",        "UKH": "East of England",
    "UKI": "London",               "UKJ": "South East England",
    "UKK": "South West England",   "UKL": "Wales",
    "UKM": "Scotland",             "UKN": "Northern Ireland",
    "UKC1": "Tees Valley and Durham",  "UKC2": "Tyne and Wear",
    "UKD1": "Cumbria",             "UKD3": "Greater Manchester",
    "UKD4": "Lancashire",          "UKD6": "Cheshire",
    "UKD7": "Merseyside",          "UKE1": "East Riding and North Lincolnshire",
    "UKE2": "North Yorkshire",     "UKE3": "South Yorkshire",
    "UKE4": "West Yorkshire",      "UKF1": "Derbyshire and Nottinghamshire",
    "UKF2": "Leicestershire and Northamptonshire", "UKF3": "Lincolnshire",
    "UKG1": "Herefordshire and Worcestershire",    "UKG2": "Shropshire and Staffordshire",
    "UKG3": "West Midlands",       "UKH1": "East Anglia",
    "UKH2": "Bedfordshire and Hertfordshire",      "UKH3": "Essex",
    "UKI3": "Inner London",        "UKI4": "Inner London",
    "UKI5": "Outer London",        "UKI6": "Outer London",
    "UKI7": "Outer London",        "UKJ1": "Berkshire and Oxfordshire",
    "UKJ2": "Surrey and Sussex",   "UKJ3": "Hampshire and Isle of Wight",
    "UKJ4": "Kent",                "UKK1": "Gloucestershire and Bristol",
    "UKK2": "Dorset and Somerset", "UKK3": "Cornwall",
    "UKK4": "Devon",               "UKL1": "West Wales",
    "UKL2": "East Wales",          "UKM2": "Eastern Scotland",
    "UKM3": "South West Scotland", "UKM5": "North East Scotland",
    "UKM6": "Highlands and Islands", "UKN0": "Northern Ireland",
}

def normalise_region(raw: str) -> str:
    if not raw:
        return ""
    r = raw.strip()
    u = r.upper()
    if u in NUTS_REGIONS:
        return NUTS_REGIONS[u]
    for length in (4, 3):
        if len(u) >= length and u[:length] in NUTS_REGIONS:
            return NUTS_REGIONS[u[:length]]
    return r

CPV_SECTORS = {
    # ── Specific 4-digit prefixes (checked first) ──
    "7995": "Events & Conferences",    # 79950000–79959999: events, exhibitions, seminars
    # ── Specific 3-digit prefixes ──
    "796": "Recruitment & Staffing",   # 79600000–79699999: all recruitment/staffing services
    "721": "IT Consultancy",           # 72100000–72199999: IT advisory & consultancy
    "722": "IT Consultancy",           # 72200000–72299999: software consultancy & development
    "831": "Management Consultancy",   # 83100000–83199999: business & management consultancy
    # ── Standard 2-digit prefixes ──
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

# ── Logging ────────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("tender_pipeline")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

log = setup_logging()

# ── OCDS extraction ────────────────────────────────────────────────────────────

def cpv_to_sector(cpv_code: str) -> str:
    if not cpv_code:
        return "Uncategorised"
    digits = cpv_code.split("-")[0].strip()
    for length in (4, 3, 2):
        if len(digits) >= length and digits[:length] in CPV_SECTORS:
            return CPV_SECTORS[digits[:length]]
    return "Other"

def extract_tender(release: dict) -> Optional[dict]:
    try:
        # Only keep active tender-stage releases; skip awards, contracts, planning etc.
        tags = release.get("tag", [])
        if isinstance(tags, str):
            tags = [tags]
        if tags and not any(tag in OPEN_TAGS for tag in tags):
            return None

        tender = release.get("tender", {})
        if not tender:
            return None
        title = tender.get("title", "").strip()
        if not title:
            return None

        # Skip cancelled, withdrawn, or completed tenders
        status = tender.get("status", "active")
        if status and status not in ("active", ""):
            return None

        parties       = release.get("parties", [])
        buyer_name    = release.get("buyer", {}).get("name", "Unknown")
        buyer_contact = {}
        buyer_address = {}
        for p in parties:
            if "buyer" in p.get("roles", []):
                buyer_name = p.get("name", buyer_name)
                cp = p.get("contactPoint", {})
                if cp:
                    buyer_contact = {
                        "name":      cp.get("name", ""),
                        "email":     cp.get("email", ""),
                        "telephone": cp.get("telephone", ""),
                    }
                addr = p.get("address", {})
                if addr:
                    buyer_address = {
                        "street":   addr.get("streetAddress", ""),
                        "locality": addr.get("locality", ""),
                        "postcode": addr.get("postalCode", ""),
                        "country":  addr.get("countryName", ""),
                    }
                break

        val            = tender.get("value", {})
        value_amount   = val.get("amount") or val.get("amountGross")
        value_currency = val.get("currency", "GBP")
        # tenderPeriod can be absent or explicitly null — guard with `or {}`
        tp = tender.get("tenderPeriod") or {}
        deadline = tp.get("endDate", "") or ""
        if not deadline:
            # Selective / competitive-flexible procedures (PA23) store their EoI
            # deadline here instead of tenderPeriod.endDate
            deadline = tender.get("expressionOfInterestDeadline", "") or ""
        if not deadline:
            # Some tenders store the deadline at lot level rather than tender level
            lot_dates = [
                (lot.get("tenderPeriod") or {}).get("endDate", "")
                for lot in tender.get("lots", [])
                if (lot.get("tenderPeriod") or {}).get("endDate", "")
            ]
            if lot_dates:
                deadline = max(lot_dates)

        cpv_code  = ""
        cpv_codes = []
        sector    = ""
        for item in tender.get("items", []):
            for cls in item.get("additionalClassifications", []):
                if cls.get("scheme") == "CPV":
                    code = cls.get("id", "")
                    if code:
                        if code not in cpv_codes:
                            cpv_codes.append(code)
                        if not cpv_code:
                            cpv_code = code
                            sector   = cpv_to_sector(cpv_code)

        if not sector:
            cat    = tender.get("mainProcurementCategory", "")
            sector = {"goods": "Goods", "services": "Services", "works": "Works"}.get(cat, "Uncategorised")

        region = ""
        for item in tender.get("items", []):
            for addr in item.get("deliveryAddresses", []):
                region = normalise_region(addr.get("region", "") or addr.get("countryName", ""))
                if region:
                    break
            if region:
                break
        if not region:
            for p in parties:
                if "buyer" in p.get("roles", []):
                    addr   = p.get("address", {})
                    region = normalise_region(addr.get("region", "") or addr.get("locality", ""))
                    break

        # Notice URL — first document pointing to a Find a Tender notice page
        url = ""
        for doc in tender.get("documents", []):
            doc_url = doc.get("url", "")
            if "find-tender.service.gov.uk/Notice/" in doc_url:
                url = doc_url
                break

        # Contract period
        cp_obj         = tender.get("contractPeriod", {})
        contract_start = cp_obj.get("startDate", "")
        contract_end   = cp_obj.get("endDate", "")

        # Procedure type
        procedure_type = tender.get("procurementMethod", "")
        procedure_desc = tender.get("procurementMethodDetails", "")

        # Award criteria
        award_criteria      = tender.get("awardCriteria", "")
        award_criteria_desc = tender.get("awardCriteriaDetails", "")

        # Lots (simplified)
        lots = []
        for lot in tender.get("lots", []):
            lv = lot.get("value", {})
            lots.append({
                "id":          lot.get("id", ""),
                "title":       lot.get("title", ""),
                "description": (lot.get("description") or "")[:300],
                "value":       lv.get("amount") or lv.get("amountGross"),
                "currency":    lv.get("currency", "GBP"),
            })

        # Documents (up to 10, public URLs only)
        documents = []
        for doc in tender.get("documents", []):
            doc_url = doc.get("url", "")
            if not doc_url:
                continue
            documents.append({
                "title": (doc.get("title") or doc.get("documentType") or "Document").strip(),
                "url":   doc_url,
                "type":  doc.get("documentType", ""),
            })
            if len(documents) >= 10:
                break

        published   = release.get("date", "")
        description = tender.get("description", "").strip()

        return {
            "id":               release.get("ocid", release.get("id", "")),
            "title":            title,
            "buyer":            buyer_name,
            "value":            value_amount,
            "currency":         value_currency,
            "deadline":         deadline,
            "sector":           sector,
            "cpvCode":          cpv_code,
            "cpvCodes":         cpv_codes,
            "region":           region or "UK",
            "url":              url,
            "published":        published,
            "description":      description[:500],
            "fullDescription":  description[:1000],
            "status":           tender.get("status", "active"),
            "procedureType":    procedure_type,
            "procedureDesc":    procedure_desc,
            "contractStart":    contract_start,
            "contractEnd":      contract_end,
            "awardCriteria":    award_criteria,
            "awardCriteriaDesc": award_criteria_desc,
            "buyerContact":     buyer_contact,
            "buyerAddress":     buyer_address,
            "lots":             lots,
            "documents":        documents,
        }
    except Exception as exc:
        log.warning(f"Skipped release: {exc}")
        return None

# ── API fetch with retry ───────────────────────────────────────────────────────

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

def fetch_page(url: str, params: Optional[dict]) -> dict:
    """Fetch one API page with exponential-backoff retries on rate-limits and transient server errors."""
    last_exc = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            log.warning(f"  Rate limited — waiting {delay}s before retry (attempt {attempt})…")
            time.sleep(delay)
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            if exc.response.status_code in RETRYABLE_STATUS_CODES:
                log.warning(f"  {exc.response.status_code} {exc.response.reason}")
                last_exc = exc
                continue  # use next retry delay
            raise  # non-retryable HTTP errors (e.g. 400, 404) fail immediately
        except Exception as exc:
            log.warning(f"  Request failed: {exc}")
            last_exc = exc
    raise RuntimeError(f"All retries exhausted: {last_exc}")


def fetch_window(date_from: str, date_to: str) -> list[dict]:
    """Fetch all pages for a given date window, return extracted tenders."""
    tenders  = []
    next_url = API_BASE
    params   = {"updatedFrom": date_from, "updatedTo": date_to, "limit": 100}
    page     = 0

    while next_url and page < MAX_PAGES:
        page += 1
        pkg      = fetch_page(next_url, params if page == 1 else None)
        releases = pkg.get("releases", [])

        if not releases:
            break

        for r in releases:
            t = extract_tender(r)
            if t:
                tenders.append(t)

        next_url = pkg.get("links", {}).get("next", "")
        if next_url:
            time.sleep(PAGE_DELAY)

    return tenders


MIN_SPLIT_WINDOW = timedelta(hours=6)  # stop bisecting once a window is this small

def fetch_window_with_fallback(date_from: str, date_to: str) -> list[dict]:
    """Try the full window; on ANY failure (corrupt page, persistent timeout, repeated
    5xx), recursively split it in half and retry each half. Bottoms out at
    MIN_SPLIT_WINDOW, where a still-failing slice is logged and skipped rather than
    aborting the whole run."""
    try:
        return fetch_window(date_from, date_to)
    except Exception as exc:
        fmt     = "%Y-%m-%dT%H:%M:%S"
        dt_from = datetime.strptime(date_from, fmt)
        dt_to   = datetime.strptime(date_to,   fmt)
        if dt_to - dt_from <= MIN_SPLIT_WINDOW:
            log.error(f"  Window {date_from} → {date_to} failed and is too small to split further: {exc} — skipping")
            return []
        log.warning(f"  Window fetch failed ({exc}) — splitting into two halves…")
        mid     = dt_from + (dt_to - dt_from) / 2
        mid_str = mid.strftime(fmt)
        results = []
        for half, f, t in [("first",  date_from, mid_str),
                            ("second", mid_str,   date_to)]:
            batch = fetch_window_with_fallback(f, t)
            log.info(f"    {half} half: {len(batch)} tenders")
            results.extend(batch)
        return results

# ── Monthly chunk helpers ──────────────────────────────────────────────────────

def month_ranges(start: datetime, end: datetime) -> list[tuple[str, str]]:
    """Return (from, to) ISO strings for each calendar month in range."""
    ranges = []
    cur = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cur < end:
        # First moment of next month
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1)
        else:
            nxt = cur.replace(month=cur.month + 1)
        chunk_end = min(nxt, end)
        ranges.append((
            cur.strftime("%Y-%m-%dT%H:%M:%S"),
            chunk_end.strftime("%Y-%m-%dT%H:%M:%S"),
        ))
        cur = nxt
    return ranges

# ── Progress file ──────────────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {"done_months": []}

def save_progress(progress: dict):
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))

# ── Disk helpers ───────────────────────────────────────────────────────────────

def load_existing() -> dict:
    if OUTPUT_FILE.exists():
        try:
            return {t["id"]: t for t in json.loads(OUTPUT_FILE.read_text()) if "id" in t}
        except Exception:
            pass
    return {}

def write_output(existing: dict, new_tenders: list[dict], now: datetime):
    for t in new_tenders:
        prev = existing.get(t["id"])
        if prev:
            # tenderUpdate releases are partial — they only contain amended fields.
            # Preserve important fields from the previous full record when the
            # update doesn't supply them, so we never lose a deadline we already had.
            for field in PRESERVE_ON_UPDATE:
                if not t.get(field) and prev.get(field):
                    t[field] = prev[field]
        existing[t["id"]] = t

    deadline_cutoff  = (now - timedelta(days=EXPIRE_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    published_cutoff = (now - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%S")
    active = [
        t for t in existing.values()
        if (t.get("deadline") and t["deadline"] >= deadline_cutoff)          # has a future deadline
        or (not t.get("deadline") and t.get("published","") >= published_cutoff)  # no deadline but published within 6 months
    ]
    active.sort(key=lambda t: t.get("published", ""), reverse=True)
    OUTPUT_FILE.write_text(json.dumps(active, separators=(',',':'), ensure_ascii=False))
    return active

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true",
                        help="Fetch all tenders from 2021 to today (resumable)")
    args = parser.parse_args()

    log.info("=" * 60)
    now = datetime.now(timezone.utc)

    if args.backfill:
        log.info("BACKFILL MODE — fetching month by month from 2021 to today")
        log.info("Safe to interrupt and resume — progress is saved after each month.")

        progress  = load_progress()
        done      = set(progress.get("done_months", []))
        existing  = load_existing()
        chunks    = month_ranges(BACKFILL_START, now)
        remaining = [(f, t) for f, t in chunks if f not in done]

        log.info(f"{len(done)}/{len(chunks)} months already done — {len(remaining)} to fetch")

        for i, (date_from, date_to) in enumerate(remaining, start=1):
            label = date_from[:7]
            log.info(f"[{i}/{len(remaining)}] Fetching {label}")
            try:
                batch = fetch_window_with_fallback(date_from, date_to)
                log.info(f"  {len(batch)} tenders — saving to disk")
                active = write_output(existing, batch, now)
                # Reload existing so next chunk merges correctly
                existing = {t["id"]: t for t in active}
                done.add(date_from)
                save_progress({"done_months": sorted(done)})
                if i < len(remaining):
                    log.info(f"  Pausing {MONTH_DELAY}s before next month…")
                    time.sleep(MONTH_DELAY)
            except Exception as exc:
                log.error(f"Failed on {label}: {exc}")
                log.error("Run again to resume from this point.")
                sys.exit(1)

        log.info(f"Backfill complete — {len(existing)} tenders in tenders.json")
        # Clean up progress file once fully done
        PROGRESS_FILE.unlink(missing_ok=True)

    else:
        log.info("Daily update starting")
        date_from = (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
        date_to   = now.strftime("%Y-%m-%dT%H:%M:%S")
        log.info(f"Fetching {date_from} → {date_to}")

        try:
            new_tenders = fetch_window(date_from, date_to)
            log.info(f"Fetched {len(new_tenders)} tenders")
        except Exception as exc:
            log.error(f"Fetch failed: {exc}")
            sys.exit(1)

        if not new_tenders:
            log.warning("No new tenders today — output unchanged")
            sys.exit(0)

        existing = load_existing()
        active   = write_output(existing, new_tenders, now)
        log.info(f"tenders.json updated — {len(active)} active tenders")

    STATE_FILE.write_text(json.dumps({
        "last_run": now.isoformat(),
        "mode":     "backfill" if args.backfill else "daily",
    }, indent=2))

    log.info("Pipeline complete")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
