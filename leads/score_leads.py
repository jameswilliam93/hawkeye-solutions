#!/usr/bin/env python3
"""
Hawkeye Solutions — tier and categorise every lead pulled so far

Combines leads/companies_house.json, leads/ccs_frameworks.json and
leads/award_notices.json into one scored dataset, tagged with where each
lead came from (source) and how good a target it is (tier):

    Tier 1 — CCS Framework supplier, OR a confirmed recent award-notice
             winner (either one is a confirmed, active public-sector
             relationship — the highest confidence available)
    Tier 2 — Companies House match, small/medium accounts category
    Tier 3 — Companies House match, everything else (micro/large/unknown)

A company on more than one CCS framework (happens — 49 companies hold
more than one of the three we've pulled) is merged into a single Tier 1
lead rather than counted twice, combining the best contact info found
across all of its framework entries.

Award-notice winners are cross-referenced by company name against the
CCS and Companies House lists (the award data has no Companies House
number to join on directly):
  - a name match against a CCS supplier gets an award note appended,
    nothing else changes — the CCS contact info is already richer
  - a name match against a Companies House Tier 2/3 lead gets PROMOTED
    to Tier 1 (unless dormant) — winning a live contract outweighs size
  - no match at all becomes a standalone Tier 1 lead, only kept if it
    has an email (otherwise there's no way to contact them at all)

Dormant companies are dropped entirely (not trading, can't be a client).
Any Companies House company that's also a CCS supplier is dropped from
the Companies House tiers so it isn't counted/imported twice.

Usage:
    python3 score_leads.py
"""

import json
import re
from pathlib import Path
from urllib.parse import unquote

CCS_FILE      = Path(__file__).parent / "ccs_frameworks.json"
CH_FILE       = Path(__file__).parent / "companies_house.json"
WEBSITE_FILE  = Path(__file__).parent / "website_enrichment.json"
AWARDS_FILE   = Path(__file__).parent / "award_notices.json"
DOMAIN_GUESSES_FILE = Path(__file__).parent / "domain_guesses.json"
OUTPUT_FILE   = Path(__file__).parent / "scored_leads.json"

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk", "outlook.com",
    "live.co.uk", "live.com", "yahoo.com", "yahoo.co.uk", "icloud.com", "aol.com",
    "btinternet.com", "virginmedia.com", "sky.com", "talktalk.net", "msn.com",
    "me.com", "mail.com",
}

TIER2_BANDS = {"small", "medium"}
TIER3_BANDS = {"micro", "large", "unknown", "unknown-full"}
EXCLUDED_BANDS = {"dormant"}


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EXCEL_ERRORS = {"#n/a", "#ref!", "#value!", "#null!", "#div/0!", "#name?", "#num!"}


def clean_email(value: str) -> str:
    """Two real sources of garbage found in practice: a source spreadsheet
    with a literal Excel error value ("#N/A") in its Email column, and a
    company's own broken mailto: link pointing at a bare domain or a first
    name instead of an actual address. Neither looks like an email, so
    don't trust anything that isn't shaped like one."""
    v = (value or "").strip()
    if not v or v.lower() in EXCEL_ERRORS:
        return ""
    return v if EMAIL_RE.match(v) else ""


def first_valid_email(values: list[str]) -> str:
    for v in values:
        cleaned = clean_email(v)
        if cleaned:
            return cleaned
    return ""


def clean_phone(value: str) -> str:
    return unquote((value or "").strip())


def domain_from_email(email: str) -> str:
    email = clean_email(email)
    if not email:
        return ""
    domain = email.split("@", 1)[1].strip().lower()
    return "" if domain in FREE_EMAIL_DOMAINS else domain


def normalise_number(num: str) -> str:
    num = (num or "").strip().upper()
    return num.zfill(8) if num.isdigit() else num


def normalise_name(name: str) -> str:
    return " ".join((name or "").strip().upper().split())


def first_nonempty(values: list[str]) -> str:
    return next((v for v in values if v), "")


def award_note(a: dict) -> str:
    return f'Won a live award: "{a["tender_title"]}" — {a["buyer"]} ({a["award_date"][:10]})'


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
            "contact_email": first_valid_email([s["contact_email"] for s in group]),
            "contact_phone": first_nonempty([clean_phone(s["contact_phone"]) for s in group]),
            "website": first_nonempty([s.get("website", "") for s in group]),
            "linkedin": first_nonempty([s.get("linkedin", "") for s in group]),
            "frameworks": sorted(set(frameworks)),
        })
    return merged


def main():
    ccs_all = json.loads(CCS_FILE.read_text())
    ch_all = json.loads(CH_FILE.read_text())
    website_by_domain = json.loads(WEBSITE_FILE.read_text()) if WEBSITE_FILE.exists() else {}
    awards = json.loads(AWARDS_FILE.read_text()) if AWARDS_FILE.exists() else []
    domain_guesses = json.loads(DOMAIN_GUESSES_FILE.read_text()) if DOMAIN_GUESSES_FILE.exists() else {}

    ccs_merged = merge_ccs_suppliers(ccs_all)
    ccs_by_name = {normalise_name(s["company_name"]): s for s in ccs_merged}
    ccs_numbers = {normalise_number(s["company_number"]) for s in ccs_merged if s["company_number"]}

    ch_name_to_number = {}
    for c in ch_all:
        ch_name_to_number.setdefault(normalise_name(c["company_name"]), normalise_number(c["company_number"]))

    # One award per company name — keep the most recent if they won more than once
    awards_by_name: dict[str, dict] = {}
    for a in awards:
        key = normalise_name(a["supplier_name"])
        existing = awards_by_name.get(key)
        if not existing or a["award_date"] > existing["award_date"]:
            awards_by_name[key] = a

    promoted_numbers: dict[str, dict] = {}
    award_note_for_ccs: dict[str, str] = {}
    standalone_awards: list[dict] = []

    for name, a in awards_by_name.items():
        if name in ccs_by_name:
            award_note_for_ccs[name] = award_note(a)
            continue
        number = ch_name_to_number.get(name)
        if number:
            promoted_numbers[number] = a
            continue
        standalone_awards.append(a)

    leads = []
    enriched_count = 0
    for s in ccs_merged:
        domain = domain_from_email(s["contact_email"])
        site = website_by_domain.get(domain) if domain else None
        website = s["website"] or (domain if site and site.get("fetched_ok") else "")
        notes = ""
        phone = s["contact_phone"]
        if site and site.get("fetched_ok"):
            notes = site.get("meta_description") or site.get("title") or ""
            if not phone and site.get("extra_phones"):
                phone = clean_phone(site["extra_phones"][0])
            enriched_count += 1
        award_bit = award_note_for_ccs.get(normalise_name(s["company_name"]))
        if award_bit:
            notes = f"{notes}\n{award_bit}".strip()
        leads.append({
            "company_name": s["company_name"],
            "company_number": s["company_number"],
            "source": "CCS Framework",
            "tier": 1,
            "size_band": None,
            "contact_name": s["contact_name"],
            "contact_email": s["contact_email"],
            "contact_phone": phone,
            "website": website,
            "linkedin": s["linkedin"],
            "frameworks": s["frameworks"],
            "region": None,
            "postal_code": "",
            "notes": notes,
        })

    counts = {
        "excluded_dormant": 0, "deduped_vs_ccs": 0, "tier2": 0, "tier3": 0,
        "unscored_band": 0, "promoted_by_award": 0,
    }

    for c in ch_all:
        number = normalise_number(c["company_number"])
        if number in ccs_numbers:
            counts["deduped_vs_ccs"] += 1
            continue
        band = c["size_band"]
        award = promoted_numbers.get(number)
        promoted = award is not None and band not in EXCLUDED_BANDS
        if band in EXCLUDED_BANDS and not promoted:
            counts["excluded_dormant"] += 1
            continue
        if promoted:
            tier = 1
            counts["promoted_by_award"] += 1
        elif band in TIER2_BANDS:
            tier = 2
            counts["tier2"] += 1
        elif band in TIER3_BANDS:
            tier = 3
            counts["tier3"] += 1
        else:
            counts["unscored_band"] += 1
            continue

        guess = domain_guesses.get(c["company_number"]) if not promoted else None
        website, notes, email, phone = "", "", "", ""
        if promoted:
            email = clean_email(award["contact_email"])
            website = award.get("website", "")
            notes = award_note(award)
        elif guess and guess.get("fetched_ok"):
            website = guess.get("domain", "")
            notes = guess.get("meta_description") or guess.get("title") or ""
            email = first_valid_email(guess.get("extra_emails") or [])
            if guess.get("extra_phones"):
                phone = clean_phone(guess["extra_phones"][0])
            counts["tier2_domain_matched"] = counts.get("tier2_domain_matched", 0) + 1

        leads.append({
            "company_name": c["company_name"],
            "company_number": c["company_number"],
            "source": "Award Notice" if promoted else "Companies House",
            "tier": tier,
            "size_band": band,
            "contact_name": "",
            "contact_email": email,
            "contact_phone": phone,
            "website": website,
            "linkedin": "",
            "frameworks": [],
            "region": c.get("locality") or c.get("region"),
            "postal_code": c.get("postal_code") or "",
            "notes": notes,
        })

    standalone_added = 0
    for a in standalone_awards:
        email = clean_email(a.get("contact_email"))
        if not email:
            continue  # no name and no usable email — nothing to contact, would be dropped at export anyway
        leads.append({
            "company_name": a["supplier_name"],
            "company_number": "",
            "source": "Award Notice",
            "tier": 1,
            "size_band": None,
            "contact_name": "",
            "contact_email": email,
            "contact_phone": "",
            "website": a.get("website", ""),
            "linkedin": "",
            "frameworks": [],
            "region": a.get("locality", ""),
            "postal_code": a.get("postal_code", ""),
            "notes": award_note(a),
        })
        standalone_added += 1

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
    print(f"  Tier 1 enriched from their own website: {enriched_count}")
    print(f"  Promoted to Tier 1 by an award win:     {counts['promoted_by_award']}")
    print(f"  Standalone award winners (no CH/CCS match, email only): {standalone_added}")
    print(f"  Tier 2 matched to a guessed-and-verified domain: {counts.get('tier2_domain_matched', 0)}")


if __name__ == "__main__":
    main()
