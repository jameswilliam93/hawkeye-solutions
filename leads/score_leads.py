#!/usr/bin/env python3
"""
Hawkeye Solutions — tier and categorise every lead pulled so far

Combines leads/companies_house.json and leads/ccs_frameworks.json into one
scored dataset, tagged with where each lead came from (source) and how
good a target it is (tier):

    Tier 1 — CCS Framework supplier (confirmed, highest confidence)
    Tier 2 — Companies House match, small/medium accounts category
    Tier 3 — Companies House match, everything else (micro/large/unknown)

A company on more than one CCS framework (happens — 49 companies hold
more than one of the three we've pulled) is merged into a single Tier 1
lead rather than counted twice, combining the best contact info found
across all of its framework entries.

Dormant companies are dropped entirely (not trading, can't be a client).
Any Companies House company that's also a CCS supplier is dropped from
the Companies House tiers so it isn't counted/imported twice.

Usage:
    python3 score_leads.py
"""

import json
from pathlib import Path

CCS_FILE    = Path(__file__).parent / "ccs_frameworks.json"
CH_FILE     = Path(__file__).parent / "companies_house.json"
OUTPUT_FILE = Path(__file__).parent / "scored_leads.json"

TIER2_BANDS = {"small", "medium"}
TIER3_BANDS = {"micro", "large", "unknown", "unknown-full"}
EXCLUDED_BANDS = {"dormant"}


def normalise_number(num: str) -> str:
    num = (num or "").strip().upper()
    return num.zfill(8) if num.isdigit() else num


def normalise_name(name: str) -> str:
    return " ".join((name or "").strip().upper().split())


def first_nonempty(values: list[str]) -> str:
    return next((v for v in values if v), "")


def merge_ccs_suppliers(ccs_all: list[dict]) -> list[dict]:
    active = [s for s in ccs_all if s["status"] == "ACTIVE"]
    groups: dict[str, list[dict]] = {}
    for s in active:
        key = normalise_name(s["trading_name"] or s["company_name"])
        groups.setdefault(key, []).append(s)

    merged = []
    for group in groups.values():
        frameworks = []
        for s in group:
            frameworks.append(s["framework"])
        merged.append({
            "company_name": first_nonempty([s["trading_name"] for s in group]),
            "company_number": first_nonempty([s["company_number"] for s in group]),
            "contact_name": first_nonempty([s["contact_name"] for s in group]),
            "contact_email": first_nonempty([s["contact_email"] for s in group]),
            "contact_phone": first_nonempty([s["contact_phone"] for s in group]),
            "website": first_nonempty([s.get("website", "") for s in group]),
            "linkedin": first_nonempty([s.get("linkedin", "") for s in group]),
            "frameworks": sorted(set(frameworks)),
        })
    return merged


def main():
    ccs_all = json.loads(CCS_FILE.read_text())
    ch_all = json.loads(CH_FILE.read_text())

    ccs_merged = merge_ccs_suppliers(ccs_all)
    ccs_numbers = {normalise_number(s["company_number"]) for s in ccs_merged if s["company_number"]}

    leads = []
    for s in ccs_merged:
        leads.append({
            "company_name": s["company_name"],
            "company_number": s["company_number"],
            "source": "CCS Framework",
            "tier": 1,
            "size_band": None,
            "contact_name": s["contact_name"],
            "contact_email": s["contact_email"],
            "contact_phone": s["contact_phone"],
            "website": s["website"],
            "linkedin": s["linkedin"],
            "frameworks": s["frameworks"],
            "region": None,
        })

    counts = {"excluded_dormant": 0, "deduped_vs_ccs": 0, "tier2": 0, "tier3": 0, "unscored_band": 0}

    for c in ch_all:
        number = normalise_number(c["company_number"])
        if number in ccs_numbers:
            counts["deduped_vs_ccs"] += 1
            continue
        band = c["size_band"]
        if band in EXCLUDED_BANDS:
            counts["excluded_dormant"] += 1
            continue
        if band in TIER2_BANDS:
            tier = 2
            counts["tier2"] += 1
        elif band in TIER3_BANDS:
            tier = 3
            counts["tier3"] += 1
        else:
            counts["unscored_band"] += 1
            continue
        leads.append({
            "company_name": c["company_name"],
            "company_number": c["company_number"],
            "source": "Companies House",
            "tier": tier,
            "size_band": band,
            "contact_name": "",
            "contact_email": "",
            "contact_phone": "",
            "website": "",
            "linkedin": "",
            "frameworks": [],
            "region": c.get("region") or c.get("locality"),
        })

    OUTPUT_FILE.write_text(json.dumps(leads, indent=2))

    by_tier = {1: 0, 2: 0, 3: 0}
    for lead in leads:
        by_tier[lead["tier"]] += 1

    print(f"Wrote {len(leads)} scored leads to {OUTPUT_FILE}")
    print(f"  Tier 1 (CCS Framework, {len(ccs_all)} raw rows merged down): {by_tier[1]}")
    print(f"  Tier 2 (CH small/medium):         {by_tier[2]}")
    print(f"  Tier 3 (CH micro/large/unknown):  {by_tier[3]}")
    print(f"  Excluded as dormant:              {counts['excluded_dormant']}")
    print(f"  Deduped (already a CCS supplier): {counts['deduped_vs_ccs']}")


if __name__ == "__main__":
    main()
