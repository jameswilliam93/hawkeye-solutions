#!/usr/bin/env python3
"""
Hawkeye Solutions — Tender Page Generator

Reads uk-tenders.json and outputs:
  tenders/<slug>/index.html  — one SEO page per tender
  sitemap.xml                — all tender URLs for Google

Usage:
    python3 generate_pages.py
    python3 generate_pages.py --output-dir /path/to/github/repo
"""

import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from html import escape as esc
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_URL   = "https://hawkeye-solutions.co.uk"
CONTACT    = "/contact.html"
INPUT_FILE = Path("uk-tenders.json")


# ── Helpers ────────────────────────────────────────────────────────────────────

def slugify(text: str, uid: str = "") -> str:
    """Convert tender title to a URL-safe slug, appended with last 6 chars of OCID."""
    s = text.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s-]+", "-", s).strip("-")
    s = s[:60].rstrip("-")
    suffix = re.sub(r"[^a-z0-9]", "", uid.lower())[-6:] if uid else ""
    return f"{s}-{suffix}" if suffix else s


def fmt_date(iso: str) -> str:
    """e.g. '2026-06-16T16:00:00+01:00' → '16 Jun 2026'"""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%-d %b %Y")
    except Exception:
        return iso[:10]


def days_until(iso: str) -> int | None:
    """Days from now until the deadline. Negative = overdue."""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (d - datetime.now(timezone.utc)).days
    except Exception:
        return None


def deadline_class(days: int | None) -> str:
    if days is None:
        return "open"
    if days <= 7:
        return "urgent"
    if days <= 21:
        return "warning"
    return "safe"


def fmt_value(amount, currency: str = "GBP") -> str:
    if amount is None:
        return ""
    try:
        v = float(amount)
        symbol = "£" if currency == "GBP" else currency + " "
        if v >= 1_000_000:
            return f"{symbol}{v/1_000_000:.1f}m"
        if v >= 1_000:
            return f"{symbol}{int(round(v/1000))}k"
        return f"{symbol}{int(v):,}"
    except Exception:
        return str(amount)


def meta_description(t: dict) -> str:
    buyer = t.get("buyer", "")
    desc  = re.sub(r"\s+", " ", (t.get("description") or "")).strip()
    dl    = fmt_date(t.get("deadline", ""))
    val   = fmt_value(t.get("value"), t.get("currency", "GBP"))

    parts = []
    if buyer:
        parts.append(f"{buyer} is seeking bids.")
    if desc:
        if len(desc) > 120:
            # Cut at the last whole word so the snippet never ends mid-word
            snippet = desc[:120].rsplit(" ", 1)[0].rstrip(" .,;:-") + "…"
        else:
            snippet = desc
        parts.append(snippet)
    if dl:
        parts.append(f"Deadline: {dl}.")
    if val:
        parts.append(f"Value: {val}.")
    parts.append("Get expert bid writing support from Hawkeye Solutions.")
    return " ".join(parts)[:300]


# ── NAV / FOOTER shared HTML ───────────────────────────────────────────────────

NAV = """\
<nav>
  <a href="/" class="nav-logo">
    <span class="nav-brand">Hawkeye Solutions</span>
  </a>
  <div class="nav-links">
    <a href="/">Home</a>
    <a href="/services.html">Services</a>
    <a href="/sectors.html">Sectors</a>
    <a href="/tender-search.html">Tender Search</a>
    <a href="/blog.html">Blog</a>
    <a href="/about.html">About Us</a>
    <a href="/contact.html" class="nav-cta">Free Consultation</a>
  </div>
  <button class="hamburger" id="ham" aria-label="Menu">
    <span></span><span></span><span></span>
  </button>
</nav>
<div class="mobile-menu" id="mob">
  <a href="/">Home</a>
  <a href="/services.html">Services</a>
  <a href="/sectors.html">Sectors</a>
  <a href="/tender-search.html">Tenders</a>
  <a href="/blog.html">Blog</a>
  <a href="/about.html">About Us</a>
  <a href="/contact.html" class="mob-cta">Free Consultation</a>
</div>"""

FOOTER = """\
<footer>
  <div class="footer-grid">
    <div class="footer-col">
      <h4>Hawkeye Solutions</h4>
      <p style="font-size:12px;line-height:1.7;color:rgba(255,255,255,0.55);margin-bottom:10px">
        Expert bid writing and tender management for UK public sector contracts.
      </p>
      <p style="font-size:12px">Tender data sourced from
        <a href="https://www.find-tender.service.gov.uk" target="_blank" rel="noopener"
           style="color:rgba(255,255,255,0.55)">Find a Tender (GOV.UK)</a>
      </p>
    </div>
    <div class="footer-col">
      <h4>Services</h4>
      <a href="/bid-writing.html">Bid Writing</a>
      <a href="/bid-management.html">Bid Management</a>
      <a href="/bid-consultancy.html">Bid Consultancy</a>
      <a href="/bid-training.html">Bid Training</a>
    </div>
    <div class="footer-col">
      <h4>Company</h4>
      <a href="/about.html">About Us</a>
      <a href="/sectors.html">Sectors</a>
      <a href="/tender-search.html">Tender Search</a>
      <a href="/blog.html">Blog</a>
    </div>
    <div class="footer-col">
      <h4>Get In Touch</h4>
      <a href="/contact.html">Free Consultation</a>
      <a href="/contact.html">Request a Call Back</a>
      <a href="/contact.html">Upload a Tender</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span>&copy; 2025 Hawkeye Solutions. All rights reserved.</span>
    <span>
      <a href="/privacy.html" style="color:rgba(255,255,255,0.45)">Privacy</a> &nbsp;·&nbsp;
      <a href="/terms.html" style="color:rgba(255,255,255,0.45)">Terms</a>
    </span>
  </div>
</footer>"""


# ── CSS ────────────────────────────────────────────────────────────────────────

CSS = """\
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --teal:#1a6b7c;--teal-dark:#0e4a57;--teal-light:#e8f4f7;--teal-mid:#2a8fa3;
  --steel:#1c3d4f;--white:#fff;--off-white:#f7fbfc;
  --text:#1a2e35;--text-muted:#4a6572;--border:#d0e8ee;
  --urgent:#c0392b;--warning:#b7670a;--safe:#1a7a50;
}
body{font-family:'Segoe UI',Arial,sans-serif;color:var(--text);background:var(--white)}
a{text-decoration:none;color:inherit}

nav{background:var(--steel);padding:0 5%;display:flex;align-items:center;justify-content:space-between;height:68px;position:sticky;top:0;z-index:100}
.nav-logo{display:flex;align-items:center;gap:12px}
.nav-brand{color:var(--white);font-size:18px;font-weight:700}
.nav-links{display:flex;gap:28px}
.nav-links a{color:rgba(255,255,255,0.85);font-size:14px;font-weight:500;transition:color .2s}
.nav-links a:hover,.nav-links a.active{color:var(--white)}
.nav-cta{background:var(--teal-mid);color:var(--white)!important;padding:8px 18px;border-radius:6px;font-size:14px;font-weight:600!important}
.hamburger{display:none;flex-direction:column;justify-content:space-between;width:24px;height:18px;background:none;border:none;cursor:pointer;padding:0;flex-shrink:0}
.hamburger span{display:block;width:100%;height:2px;background:var(--white);border-radius:2px;transition:transform .25s,opacity .25s}
.hamburger.open span:nth-child(1){transform:translateY(8px) rotate(45deg)}
.hamburger.open span:nth-child(2){opacity:0}
.hamburger.open span:nth-child(3){transform:translateY(-8px) rotate(-45deg)}
.mobile-menu{display:none;position:absolute;top:68px;left:0;right:0;background:var(--steel);z-index:99;flex-direction:column;border-top:1px solid rgba(255,255,255,0.1);box-shadow:0 8px 24px rgba(0,0,0,0.2)}
.mobile-menu.open{display:flex}
.mobile-menu a{color:rgba(255,255,255,0.85);font-size:15px;font-weight:500;padding:14px 5%;border-bottom:1px solid rgba(255,255,255,0.07)}
.mobile-menu a:last-child{border-bottom:none}
.mobile-menu a:hover{background:rgba(255,255,255,0.07);color:var(--white)}
.mob-cta{background:var(--teal-mid);color:var(--white)!important;margin:12px 5%;border-radius:6px;text-align:center;border-bottom:none!important;padding:12px 5%}

.hero{background:linear-gradient(135deg,var(--steel) 0%,var(--teal-dark) 60%,var(--teal) 100%);padding:48px 5% 40px}
.breadcrumb{font-size:13px;color:rgba(255,255,255,0.6);margin-bottom:16px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.breadcrumb a{color:rgba(255,255,255,0.6);transition:color .15s}
.breadcrumb a:hover{color:var(--white)}
.breadcrumb span{color:rgba(255,255,255,0.35)}
.hero-badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.hero-badge{display:inline-block;padding:3px 12px;border-radius:20px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.4px}
.badge-live{background:rgba(100,220,120,0.2);color:#7dd464}
.badge-closed{background:rgba(200,80,80,0.2);color:#f08080}
.badge-sector{background:rgba(232,244,247,0.2);color:#a0d8e8}
.badge-region{background:rgba(255,255,255,0.12);color:rgba(255,255,255,0.75)}
.hero h1{font-size:clamp(22px,3.5vw,36px);font-weight:800;color:var(--white);line-height:1.25;margin-bottom:8px}
.hero-buyer{font-size:15px;color:rgba(255,255,255,0.75);margin-bottom:18px}
.hero-ref{display:inline-block;background:rgba(255,255,255,0.12);color:rgba(255,255,255,0.8);font-size:12px;font-weight:600;padding:4px 12px;border-radius:6px;font-family:monospace;letter-spacing:.3px}

.page-wrap{max-width:980px;margin:0 auto;padding:40px 5% 60px;display:grid;grid-template-columns:1fr 320px;gap:32px;align-items:start}
.main-col{}
.side-col{}

.block{background:var(--white);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:20px}
.block h2{font-size:16px;font-weight:700;color:var(--steel);margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.block p{font-size:14px;color:var(--text-muted);line-height:1.85}

.dl-box{border-radius:12px;padding:18px 20px;margin-bottom:20px;display:flex;align-items:center;gap:20px}
.dl-box.urgent{border:1px solid #f0a0a0;background:#fdf0ee}
.dl-box.warning{border:1px solid #f0c070;background:#fef6e8}
.dl-box.safe{border:1px solid #a3dcc0;background:#e8f7f0}
.dl-box.open{border:1px solid var(--border);background:var(--off-white)}
.dl-box.closed{border:1px solid #d0d0d0;background:#f5f5f5}
.dl-days{font-size:36px;font-weight:800;line-height:1}
.dl-days.urgent{color:var(--urgent)}
.dl-days.warning{color:var(--warning)}
.dl-days.safe{color:var(--safe)}
.dl-days.closed{color:#999}
.dl-sub{font-size:11px;color:var(--text-muted);margin-top:3px}
.dl-label{font-size:12px;color:var(--text-muted);margin-bottom:3px}
.dl-date{font-size:15px;font-weight:700;color:var(--steel)}

.fact-row{display:flex;gap:16px;padding:10px 0;border-bottom:1px solid var(--border);font-size:13px}
.fact-row:last-child{border-bottom:none;padding-bottom:0}
.fact-row:first-child{padding-top:0}
.fact-label{font-weight:600;color:var(--steel);width:130px;flex-shrink:0}
.fact-value{color:var(--text-muted);flex:1;word-break:break-word}

.cta-box{background:linear-gradient(135deg,var(--teal-dark),var(--teal-mid));border-radius:12px;padding:24px;margin-bottom:20px;text-align:center}
.cta-box h3{color:var(--white);font-size:17px;font-weight:800;margin-bottom:8px}
.cta-box p{color:rgba(255,255,255,0.8);font-size:13px;line-height:1.6;margin-bottom:18px}
.btn{display:block;width:100%;padding:12px 16px;border-radius:7px;font-size:14px;font-weight:700;text-align:center;transition:background .18s,opacity .18s;border:none;cursor:pointer;font-family:inherit;text-decoration:none}
.btn-white{background:var(--white);color:var(--teal-dark)}
.btn-white:hover{background:var(--teal-light)}
.btn-outline{background:transparent;border:1.5px solid rgba(255,255,255,0.5);color:var(--white);margin-top:8px}
.btn-outline:hover{background:rgba(255,255,255,0.12)}
.btn-primary{background:var(--teal-dark);color:var(--white);margin-bottom:8px}
.btn-primary:hover{background:var(--teal)}
.btn-secondary{background:transparent;border:1.5px solid var(--teal-mid);color:var(--teal-dark)}
.btn-secondary:hover{background:var(--teal-light)}

.lot{background:var(--off-white);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:8px}
.lot-title{font-size:13px;font-weight:700;color:var(--steel);margin-bottom:2px}
.lot-val{font-size:13px;font-weight:800;color:var(--teal-dark);margin-bottom:6px}
.lot-desc{font-size:12px;color:var(--text-muted);line-height:1.6}
.doc-link{display:flex;align-items:flex-start;gap:8px;padding:9px 12px;border:1px solid var(--border);border-radius:7px;margin-bottom:6px;font-size:13px;color:var(--teal-dark);background:var(--white);transition:background .15s;word-break:break-word}
.doc-link:hover{background:var(--teal-light);border-color:var(--teal-mid)}

.back-link{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--teal);font-weight:600;margin-bottom:20px}
.back-link:hover{text-decoration:underline}

.cta-banner{background:linear-gradient(135deg,var(--teal-dark),var(--teal-mid));padding:60px 5%;text-align:center;margin-top:0}
.cta-banner h2{font-size:28px;font-weight:800;color:var(--white);margin-bottom:10px}
.cta-banner p{font-size:15px;color:rgba(255,255,255,0.8);margin-bottom:24px}
.btn-white-lg{background:var(--white);color:var(--teal-dark);padding:13px 28px;border-radius:7px;font-weight:700;font-size:15px;display:inline-block;transition:background .2s}
.btn-white-lg:hover{background:var(--teal-light)}

footer{background:var(--steel);color:rgba(255,255,255,0.6);padding:36px 5% 24px}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px;margin-bottom:28px}
.footer-col h4{color:var(--white);font-size:14px;font-weight:700;margin-bottom:12px}
.footer-col a{display:block;font-size:13px;color:rgba(255,255,255,0.55);margin-bottom:7px;transition:color .2s}
.footer-col a:hover{color:var(--white)}
.footer-bottom{border-top:1px solid rgba(255,255,255,0.1);padding-top:18px;font-size:12px;display:flex;justify-content:space-between}

@media(max-width:768px){
  nav .nav-links{display:none}
  .hamburger{display:flex}
  .page-wrap{grid-template-columns:1fr;padding:24px 5% 48px}
  .side-col{order:-1}
  .footer-grid{grid-template-columns:1fr 1fr}
  .footer-bottom{flex-direction:column;gap:8px}
}"""


# ── Page builder ───────────────────────────────────────────────────────────────

def build_page(t: dict, slug: str, is_closed: bool) -> str:
    title_raw  = t.get("title", "UK Government Tender")
    buyer      = t.get("buyer", "")
    deadline   = t.get("deadline", "")
    value      = fmt_value(t.get("value"), t.get("currency", "GBP"))
    sector     = t.get("sector", "")
    region     = t.get("region", "")
    desc       = (t.get("fullDescription") or t.get("description") or "").strip()
    url        = t.get("url", "")
    ref        = t.get("id", "")
    procedure  = t.get("procedureDesc") or t.get("procedureType") or ""
    contract_s = fmt_date(t.get("contractStart", ""))
    contract_e = fmt_date(t.get("contractEnd", ""))
    lots       = t.get("lots", []) or []
    documents  = t.get("documents", []) or []
    contact    = t.get("buyerContact", {}) or {}
    address    = t.get("buyerAddress", {}) or {}
    published  = fmt_date(t.get("published", ""))

    days       = days_until(deadline)
    dl_cls     = "closed" if is_closed else deadline_class(days)
    page_url   = f"{BASE_URL}/tenders/{slug}/"
    meta_desc  = meta_description(t)

    # ── Deadline box ──────────────────────────────────────────────────────────
    if is_closed:
        dl_html = f"""
<div class="dl-box closed">
  <div style="text-align:center;width:60px;flex-shrink:0">
    <div class="dl-days closed">✕</div>
    <div class="dl-sub">Closed</div>
  </div>
  <div>
    <div class="dl-label">Submission deadline</div>
    <div class="dl-date">{esc(fmt_date(deadline))}</div>
  </div>
</div>"""
    elif deadline:
        days_label = f"{abs(days)} day{'s' if abs(days) != 1 else ''}"
        dl_html = f"""
<div class="dl-box {dl_cls}">
  <div style="text-align:center;width:60px;flex-shrink:0">
    <div class="dl-days {dl_cls}">{days}</div>
    <div class="dl-sub">days left</div>
  </div>
  <div>
    <div class="dl-label">Submission deadline</div>
    <div class="dl-date">{esc(fmt_date(deadline))}</div>
  </div>
</div>"""
    else:
        dl_html = ""

    # ── CTA box ───────────────────────────────────────────────────────────────
    if is_closed:
        cta_html = f"""
<div class="cta-box">
  <h3>This tender has closed</h3>
  <p>We can help you find and win similar contracts. Get in touch for a free consultation.</p>
  <a href="{CONTACT}" class="btn btn-white">Find Similar Opportunities</a>
</div>"""
    else:
        full_tender_btn = (
            f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer" '
            f'class="btn btn-primary">View Official Tender Notice</a>'
            if url else
            '<button class="btn btn-primary" style="opacity:.4;cursor:not-allowed" disabled>'
            'Official Notice (link pending)</button>'
        )
        cta_html = f"""
<div class="cta-box">
  <h3>Need help winning this bid?</h3>
  <p>Our expert bid writers have helped clients win contracts just like this one. Don't leave it to chance.</p>
  <a href="{CONTACT}" class="btn btn-white">Get a Free Bid Review</a>
  <a href="{CONTACT}" class="btn btn-outline">Enquire About This Bid</a>
</div>
<div class="block" style="margin-bottom:20px">
  {full_tender_btn}
  <a href="{CONTACT}" class="btn btn-secondary" style="margin-top:8px;display:block;text-align:center;padding:12px 16px">Enquire About This Bid</a>
</div>"""

    # ── Key facts ─────────────────────────────────────────────────────────────
    facts = []
    if buyer:
        facts.append(("Buyer", esc(buyer)))
    if value:
        facts.append(("Contract Value", esc(value)))
    if sector:
        facts.append(("Sector", esc(sector)))
    if region and region != "UK":
        facts.append(("Region", esc(region)))
    if procedure:
        facts.append(("Procedure", esc(procedure)))
    if contract_s or contract_e:
        period = " – ".join(filter(None, [contract_s, contract_e]))
        facts.append(("Contract Period", esc(period)))
    if published:
        facts.append(("Published", esc(published)))
    if ref:
        facts.append(("Reference", f"<code style='font-size:12px;font-family:monospace'>{esc(ref)}</code>"))

    facts_rows = "".join(
        f'<div class="fact-row"><span class="fact-label">{lbl}</span>'
        f'<span class="fact-value">{val}</span></div>'
        for lbl, val in facts
    )

    # ── Lots ─────────────────────────────────────────────────────────────────
    lots_html = ""
    if lots:
        lot_items = ""
        for lot in lots:
            lv = fmt_value(lot.get("value"), lot.get("currency", "GBP"))
            lt = esc(lot.get("title") or f"Lot {lot.get('id','')}")
            ld = esc((lot.get("description") or "")[:200])
            lot_items += f"""
<div class="lot">
  <div class="lot-title">{lt}</div>
  {f'<div class="lot-val">{lv}</div>' if lv else ''}
  {f'<div class="lot-desc">{ld}</div>' if ld else ''}
</div>"""
        lots_html = f"""
<div class="block">
  <h2>Lots ({len(lots)})</h2>
  {lot_items}
</div>"""

    # ── Documents ─────────────────────────────────────────────────────────────
    docs_html = ""
    if documents:
        doc_items = ""
        for doc in documents[:8]:
            doc_url   = doc.get("url", "")
            doc_title = esc(doc.get("title") or doc.get("type") or "Document")
            if doc_url:
                doc_items += (
                    f'<a href="{esc(doc_url)}" target="_blank" rel="noopener" class="doc-link">'
                    f'<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" '
                    f'viewBox="0 0 24 24" style="flex-shrink:0;margin-top:1px">'
                    f'<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>'
                    f'<polyline points="14 2 14 8 20 8"/></svg>{doc_title}</a>'
                )
        if doc_items:
            docs_html = f"""
<div class="block">
  <h2>Documents &amp; Links</h2>
  {doc_items}
</div>"""

    # ── Buyer contact ─────────────────────────────────────────────────────────
    contact_rows = ""
    if contact.get("name"):
        contact_rows += f'<div class="fact-row"><span class="fact-label">Contact</span><span class="fact-value">{esc(contact["name"])}</span></div>'
    if contact.get("email"):
        contact_rows += f'<div class="fact-row"><span class="fact-label">Email</span><span class="fact-value"><a href="mailto:{esc(contact["email"])}" style="color:var(--teal)">{esc(contact["email"])}</a></span></div>'
    if contact.get("telephone"):
        contact_rows += f'<div class="fact-row"><span class="fact-label">Phone</span><span class="fact-value">{esc(contact["telephone"])}</span></div>'
    if address.get("locality"):
        contact_rows += f'<div class="fact-row"><span class="fact-label">Location</span><span class="fact-value">{esc(address.get("locality",""))}{", " + esc(address.get("postcode","")) if address.get("postcode") else ""}</span></div>'

    buyer_block = f"""
<div class="block">
  <h2>Buyer Information</h2>
  {contact_rows if contact_rows else f'<p>{esc(buyer)}</p>'}
</div>""" if (buyer or contact_rows) else ""

    # ── Description ───────────────────────────────────────────────────────────
    desc_html = ""
    if desc:
        desc_html = f"""
<div class="block">
  <h2>Tender Description</h2>
  <p style="white-space:pre-wrap;word-break:break-word">{esc(desc)}</p>
</div>"""

    # ── Hero badges ───────────────────────────────────────────────────────────
    status_badge = '<span class="hero-badge badge-closed">Closed</span>' if is_closed else '<span class="hero-badge badge-live">Live</span>'
    sector_badge = f'<span class="hero-badge badge-sector">{esc(sector)}</span>' if sector else ""
    region_badge = f'<span class="hero-badge badge-region">{esc(region)}</span>' if region and region != "UK" else ""

    # ── JSON-LD structured data ───────────────────────────────────────────────
    jsonld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title_raw,
        "description": meta_desc,
        "url": page_url,
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": BASE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "Tender Search", "item": BASE_URL + "/tender-search.html"},
                {"@type": "ListItem", "position": 3, "name": title_raw, "item": page_url},
            ]
        }
    }
    if buyer:
        jsonld["author"] = {"@type": "Organization", "name": buyer}
    if deadline:
        jsonld["expires"] = deadline

    # ── SEO title ─────────────────────────────────────────────────────────────
    seo_title = f"{title_raw}"
    if buyer:
        seo_title += f" – {buyer}"
    seo_title += " | UK Government Tender | Hawkeye Solutions"
    if len(seo_title) > 65:
        if len(title_raw) > 52:
            seo_title = f"{title_raw[:52].rstrip()}… | Hawkeye Solutions"
        else:
            seo_title = f"{title_raw} | Hawkeye Solutions"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(seo_title)}</title>
<meta name="description" content="{esc(meta_desc)}">
<link rel="canonical" href="{esc(page_url)}">
<link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96">
<link rel="shortcut icon" href="/favicon.ico">
<meta property="og:title" content="{esc(title_raw)}">
<meta property="og:description" content="{esc(meta_desc)}">
<meta property="og:url" content="{esc(page_url)}">
<meta property="og:type" content="website">
<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
<style>{CSS}</style>
</head>
<body>
{NAV}

<div class="hero">
  <div class="breadcrumb">
    <a href="/">Home</a>
    <span>›</span>
    <a href="/tender-search.html">Tender Search</a>
    <span>›</span>
    <span style="color:rgba(255,255,255,0.85)">{esc(title_raw[:60])}{'…' if len(title_raw)>60 else ''}</span>
  </div>
  <div class="hero-badges">{status_badge}{sector_badge}{region_badge}</div>
  <h1>{esc(title_raw)}</h1>
  {f'<div class="hero-buyer">{esc(buyer)}</div>' if buyer else ''}
  {f'<div class="hero-ref">{esc(ref)}</div>' if ref else ''}
</div>

<div class="page-wrap">

  <div class="main-col">
    <a href="/tender-search.html" class="back-link">
      ← Back to all tenders
    </a>

    {desc_html}

    {lots_html}

    {docs_html}

    {buyer_block}

    <div class="block">
      <h2>Key Facts</h2>
      {facts_rows}
    </div>
  </div>

  <div class="side-col">
    {dl_html}
    {cta_html}
  </div>

</div>

<div class="cta-banner">
  <h2>Don't Miss Your Next Contract</h2>
  <p>Hawkeye Solutions helps businesses win UK public sector tenders. From bid writing to full tender management.</p>
  <a href="/contact.html" class="btn-white-lg">Get a Free Consultation</a>
</div>

{FOOTER}

<script>
const ham = document.getElementById('ham');
const mob = document.getElementById('mob');
ham.addEventListener('click', () => {{
  ham.classList.toggle('open');
  mob.classList.toggle('open');
}});
</script>
</body>
</html>"""


# ── Sitemap builder ────────────────────────────────────────────────────────────

def build_sitemap(entries: list[tuple[str, str]]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls  = "\n".join(
        f"  <url>\n"
        f"    <loc>{BASE_URL}/tenders/{slug}/</loc>\n"
        f"    <lastmod>{lastmod or today}</lastmod>\n"
        f"    <changefreq>weekly</changefreq>\n"
        f"    <priority>0.7</priority>\n"
        f"  </url>"
        for slug, lastmod in entries
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",      default=str(INPUT_FILE))
    parser.add_argument("--output-dir", default=".",
                        help="Root of the GitHub repo (where tenders/ folder will be created)")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text())
    out  = Path(args.output_dir)
    now  = datetime.now(timezone.utc)

    generated = 0
    skipped   = 0
    sitemap_entries: list[tuple[str, str]] = []
    seen_slugs: set[str] = set()

    for t in data:
        title = t.get("title", "").strip()
        if len(title) < 5:
            skipped += 1
            continue

        deadline = t.get("deadline", "")
        is_closed = False
        if deadline:
            try:
                dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=timezone.utc)
                if dl < now:
                    is_closed = True
            except Exception:
                pass

        slug = slugify(title, t.get("id", ""))
        # Guarantee uniqueness within this run
        base_slug = slug
        n = 2
        while slug in seen_slugs:
            slug = f"{base_slug}-{n}"
            n += 1
        seen_slugs.add(slug)

        page_dir = out / "tenders" / slug
        page_dir.mkdir(parents=True, exist_ok=True)

        html = build_page(t, slug, is_closed)
        (page_dir / "index.html").write_text(html, encoding="utf-8")

        published = (t.get("published") or "")[:10]
        sitemap_entries.append((slug, published))
        generated += 1

    # Write sitemap
    sitemap_path = out / "sitemap.xml"
    sitemap_path.write_text(build_sitemap(sitemap_entries), encoding="utf-8")

    print(f"Generated {generated} tender pages → {out}/tenders/")
    print(f"Sitemap   → {sitemap_path}  ({len(sitemap_entries)} URLs)")
    if skipped:
        print(f"Skipped   {skipped} tenders (no title)")


if __name__ == "__main__":
    main()
