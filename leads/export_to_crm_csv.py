#!/usr/bin/env python3
"""
Hawkeye Solutions — build a CRM-ready CSV from leads/scored_leads.json

Exports Tier 1 (CCS Framework) and Tier 2 (Companies House, small/medium,
now director-enriched) leads in the column format hawkeye-crm's Import CSV
expects. Tier 3 is left out by default — those have no contact name yet,
so they'd all fail the CRM's import validation anyway.

Usage:
    python3 export_to_crm_csv.py                  # Tier 1 + 2
    python3 export_to_crm_csv.py --tiers 1 2 3     # include Tier 3 too
"""

import argparse
import csv
from pathlib import Path
import json

SCORED_FILE = Path(__file__).parent / "scored_leads.json"
OUTPUT_FILE = Path(__file__).parent / "crm_import_leads.csv"

CSV_HEADERS = [
    "Company", "Contact Name", "Title", "Email", "Phone", "LinkedIn",
    "Location", "Company Size", "Website", "Industry", "Stage", "Source",
    "Current Supplier", "Contract End", "Frameworks", "Tags",
]

SIZE_BAND_TO_CRM = {
    "micro": "1-10",
    "small": "11-50",
    "medium": "51-200",
    "large": "200+",
}

SOURCE_TO_CRM = {
    "CCS Framework": "Framework",
    "Companies House": "Scraped",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiers", nargs="+", type=int, default=[1, 2])
    args = parser.parse_args()

    leads = json.loads(SCORED_FILE.read_text())

    rows = []
    skipped_no_contact = 0
    for lead in leads:
        if lead["tier"] not in args.tiers:
            continue
        contact_name = lead["contact_name"]
        if not contact_name and lead["contact_email"]:
            # No named person published (e.g. RM6376 gives only a company inbox) —
            # an honest placeholder beats inventing a fake name, and still satisfies
            # the CRM's required Contact Name field.
            contact_name = "Recruitment Team"
        if not contact_name:
            skipped_no_contact += 1
            continue
        tags = [f"tier-{lead['tier']}"]
        if lead["tier"] == 1:
            tags.append("framework")
        rows.append({
            "Company": lead["company_name"],
            "Contact Name": contact_name,
            "Title": "",
            "Email": lead["contact_email"],
            "Phone": lead["contact_phone"],
            "LinkedIn": lead.get("linkedin") or "",
            "Location": lead.get("region") or "",
            "Company Size": SIZE_BAND_TO_CRM.get(lead.get("size_band"), ""),
            "Website": lead.get("website") or "",
            "Industry": "Recruitment & Staffing",
            "Stage": "New Lead",
            "Source": SOURCE_TO_CRM.get(lead["source"], "Other"),
            "Current Supplier": "",
            "Contract End": "",
            "Frameworks": "|".join(lead.get("frameworks") or []),
            "Tags": "|".join(tags),
        })

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")
    if skipped_no_contact:
        print(f"Skipped {skipped_no_contact} leads with no contact name (mostly Tier 3)")
    by_tier = {}
    for row in rows:
        for tag in row["Tags"].split("|"):
            if tag.startswith("tier-"):
                by_tier[tag] = by_tier.get(tag, 0) + 1
    for tier, count in sorted(by_tier.items()):
        print(f"  {tier}: {count}")


if __name__ == "__main__":
    main()
