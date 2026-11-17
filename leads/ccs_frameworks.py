#!/usr/bin/env python3
"""
Hawkeye Solutions — CCS/GCA recruitment framework supplier pull (multi-framework)

Several CCS/GCA frameworks publish an official supplier spreadsheet with real
business contact data. Each one happens to structure its spreadsheet
differently, so each has its own small parser below, but they share the same
download/output pipeline.

Frameworks covered so far (all confirmed to have a public, contact-bearing
supplier file as of 2026-11):
    RM6277  Non Clinical Staffing              — contact name/email/phone
    RM6290  Executive & Non-Executive Recruitment — contact/email/phone/website/LinkedIn
    RM6376  Supply Teachers & Education Recruitment — company email + CH number

Checked and skipped (no public supplier spreadsheet found, just buyer
guides/templates): RM6288 Workforce Solutions, RM6281 Clinical and
Healthcare Staffing. Revisit later if CCS publishes one, or if a
name-only /suppliers page is worth combining with the Companies House
director lookup the way Tier 2 leads are.

Usage:
    python3 ccs_frameworks.py
"""

import json
import logging
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

import requests

OUTPUT_FILE = Path(__file__).parent / "ccs_frameworks.json"
LOG_FILE    = Path(__file__).parent / "ccs_frameworks.log"
TIMEOUT     = 30

TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
TEXT_NS  = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
NS = {"table": TABLE_NS, "text": TEXT_NS}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ccs_frameworks")


def find_asset_url(session: requests.Session, rm_code: str, filename_fragment: str) -> str:
    page_url = f"https://www.gca.gov.uk/agreements/{rm_code}"
    resp = session.get(page_url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    pattern = re.compile(
        rf'https://assets\.(?:gca|crowncommercial)\.gov\.uk/wp-content/uploads/'
        rf'{re.escape(rm_code)}[^"]*{re.escape(filename_fragment)}[^"]*\.(?:ods|xlsx)'
    )
    match = pattern.search(resp.text)
    if not match:
        raise RuntimeError(f"Could not find a '{filename_fragment}' file on {page_url}")
    return match.group(0)


def download_ods_tables(session: requests.Session, url: str) -> dict[str, ET.Element]:
    resp = session.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    with zipfile.ZipFile(BytesIO(resp.content)) as z:
        content = z.read("content.xml")
    root = ET.fromstring(content)
    tables = root.findall(".//table:table", NS)
    return {t.get(f"{{{TABLE_NS}}}name"): t for t in tables}


def expand_row(row: ET.Element) -> list[str]:
    values: list[str] = []
    for cell in row.findall("table:table-cell", NS):
        repeat = int(cell.get(f"{{{TABLE_NS}}}number-columns-repeated", 1))
        paragraphs = cell.findall(".//text:p", NS)
        text = " ".join((p.text or "") for p in paragraphs)
        values.extend([text] * repeat)
    return values


def sheet_rows(sheet: ET.Element) -> list[list[str]]:
    return [expand_row(r) for r in sheet.findall("table:table-row", NS)]


def find_header_row(rows: list[list[str]], must_contain: str, search_rows: int = 5) -> int:
    """Not every sheet puts its header on row 0 — some have a blank leading row."""
    for i, row in enumerate(rows[:search_rows]):
        if must_contain in row:
            return i
    raise RuntimeError(f"No row containing '{must_contain}' found in the first {search_rows} rows")


def col_index(header: list[str], name: str, required: bool = True) -> int | None:
    try:
        return header.index(name)
    except ValueError:
        if required:
            raise RuntimeError(f"Expected column '{name}' not found in header: {header}")
        return None


def get(vals: list[str], i: int | None) -> str:
    if i is None or i >= len(vals):
        return ""
    return vals[i].strip()


# ── Per-framework parsers ────────────────────────────────────────────────

def parse_rm6277(session: requests.Session) -> list[dict]:
    url = find_asset_url(session, "RM6277", "Supplier-lot-matrix-and-contacts")
    log.info("RM6277: downloading %s", url)
    tables = download_ods_tables(session, url)
    rows = sheet_rows(tables["Supplier_Matrix"])
    header = [h.strip() for h in rows[0]]
    idx = {
        "status": col_index(header, "Status"),
        "company": col_index(header, "Supplier Name"),
        "trading": col_index(header, "Trading Name"),
        "number": col_index(header, "Company number"),
        "contact": col_index(header, "Contact name"),
        "email": col_index(header, "Contact email"),
        "phone": col_index(header, "Contact phone number"),
    }
    lot_cols = [(i, h) for i, h in enumerate(header) if h.startswith("Lot ")]

    records = []
    for vals in rows[1:]:
        company = get(vals, idx["company"])
        if not company:
            continue
        lots = [h for i, h in lot_cols if get(vals, i).lower() == "yes"]
        records.append({
            "company_name": company,
            "trading_name": get(vals, idx["trading"]) or company,
            "company_number": get(vals, idx["number"]),
            "contact_name": get(vals, idx["contact"]),
            "contact_email": get(vals, idx["email"]),
            "contact_phone": get(vals, idx["phone"]),
            "website": "",
            "linkedin": "",
            "status": get(vals, idx["status"]) or "ACTIVE",
            "lots": lots,
            "framework": "CCS RM6277",
        })
    return records


def parse_rm6290(session: requests.Session) -> list[dict]:
    url = find_asset_url(session, "RM6290", "Supplier-capability-matrix")
    log.info("RM6290: downloading %s", url)
    tables = download_ods_tables(session, url)

    records = []
    for sheet_name, sheet in tables.items():
        if not sheet_name or not sheet_name.startswith("Contact_Details_Lot_"):
            continue
        lot = sheet_name.replace("Contact_Details_", "").replace("_", " ")
        rows = sheet_rows(sheet)
        header_row_idx = find_header_row(rows, "Supplier Name")
        header = [h.strip() for h in rows[header_row_idx]]
        idx = {
            "company": col_index(header, "Supplier Name"),
            "contact": col_index(header, "Framework Contact", required=False),
            "email": col_index(header, "Contact Email", required=False),
            "phone": col_index(header, "Phone Number", required=False),
            "address": col_index(header, "Address", required=False),
            "website": col_index(header, "Website", required=False),
            "linkedin": col_index(header, "Linked In", required=False),
        }
        current_company = ""
        for vals in rows[header_row_idx + 1:]:
            company = get(vals, idx["company"]) or current_company
            if not company:
                continue
            current_company = company
            contact = get(vals, idx["contact"])
            if not contact and not get(vals, idx["email"]):
                continue
            records.append({
                "company_name": company,
                "trading_name": company,
                "company_number": "",
                "contact_name": contact,
                "contact_email": get(vals, idx["email"]),
                "contact_phone": get(vals, idx["phone"]),
                "website": get(vals, idx["website"]),
                "linkedin": get(vals, idx["linkedin"]),
                "status": "ACTIVE",
                "lots": [lot],
                "framework": "CCS RM6290",
            })
    return records


def parse_rm6376(session: requests.Session) -> list[dict]:
    url = find_asset_url(session, "RM6376", "Outcome-Supplier-list")
    log.info("RM6376: downloading %s", url)
    tables = download_ods_tables(session, url)

    records = []
    for sheet_name, sheet in tables.items():
        if not sheet_name or "LOT" not in sheet_name.upper():
            continue
        rows = sheet_rows(sheet)
        header_row_idx = find_header_row(rows, "Registered Name")
        header = [h.strip() for h in rows[header_row_idx]]
        idx = {
            "company": col_index(header, "Registered Name"),
            "address": col_index(header, "Address", required=False),
            "number": col_index(header, "RegistrationNumber", required=False),
            "email": col_index(header, "Email Address", required=False),
        }
        for vals in rows[header_row_idx + 1:]:
            company = get(vals, idx["company"])
            if not company:
                continue
            records.append({
                "company_name": company,
                "trading_name": company,
                "company_number": get(vals, idx["number"]),
                "contact_name": "",
                "contact_email": get(vals, idx["email"]),
                "contact_phone": "",
                "website": "",
                "linkedin": "",
                "status": "ACTIVE",
                "lots": [sheet_name],
                "framework": "CCS RM6376",
            })
    return records


FRAMEWORK_PARSERS = {
    "RM6277": parse_rm6277,
    "RM6290": parse_rm6290,
    "RM6376": parse_rm6376,
}


def main():
    session = requests.Session()
    all_records = []
    for rm_code, parser in FRAMEWORK_PARSERS.items():
        try:
            records = parser(session)
            log.info("%s: %d records", rm_code, len(records))
            all_records.extend(records)
        except Exception as e:
            log.error("%s: failed — %s", rm_code, e)

    OUTPUT_FILE.write_text(json.dumps(all_records, indent=2))
    log.info("Done. %d total records written to %s", len(all_records), OUTPUT_FILE)
    by_framework = {}
    for r in all_records:
        by_framework[r["framework"]] = by_framework.get(r["framework"], 0) + 1
    for fw, count in sorted(by_framework.items()):
        log.info("  %-14s %d", fw, count)
    with_email = sum(1 for r in all_records if r["contact_email"])
    log.info("%d/%d have a contact email", with_email, len(all_records))


if __name__ == "__main__":
    main()
