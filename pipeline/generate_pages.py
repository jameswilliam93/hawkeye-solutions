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
        if v >= 1_000_000_000:
            return f"{symbol}{v/1_000_000_000:.1f}bn"
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
    <img src="/logo.png" alt="Hawkeye Solutions" height="36" style="display:block">
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
  --text:#1a2e35;--text-muted:#4a6572;--border:#d8ecf0;
  --urgent:#c0392b;--warning:#b7670a;--safe:#1a7a50;
  --font-display:'Source Serif 4',Georgia,'Times New Roman',serif;
}
body{font-family:'Segoe UI',Arial,sans-serif;color:var(--text);background:var(--white)}
a{text-decoration:none;color:inherit}

::selection{background:var(--teal-mid);color:var(--white)}
:focus-visible{outline:2px solid var(--teal-mid);outline-offset:2px}
html{scrollbar-color:var(--teal-mid) var(--off-white)}
::-webkit-scrollbar{width:12px;height:12px}
::-webkit-scrollbar-track{background:var(--off-white)}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:20px;border:3px solid var(--off-white)}
::-webkit-scrollbar-thumb:hover{background:var(--teal-mid)}

nav{background:var(--steel);padding:0 5%;display:flex;align-items:center;justify-content:space-between;height:68px;position:sticky;top:0;z-index:100}
.nav-logo{display:flex;align-items:center;gap:12px}
.nav-brand{font-family:var(--font-display);color:var(--white);font-size:18px;font-weight:600}
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

.wrap{max-width:1180px;margin:0 auto;padding:0 5%}

.hero{background:var(--steel);padding:30px 0 0;position:relative;overflow:hidden}
.hero::before{
  content:'';position:absolute;top:-18%;right:-6%;width:420px;height:420px;
  background:url('/logo.png') no-repeat center/contain;
  opacity:0.1;filter:grayscale(1) brightness(2.4);
}
.hero-inner{max-width:1180px;margin:0 auto;padding:0 5% 26px;position:relative;z-index:1}
.breadcrumb{font-size:13px;color:rgba(255,255,255,0.6);margin-bottom:14px;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.breadcrumb a{color:rgba(255,255,255,0.6);transition:color .15s}
.breadcrumb a:hover{color:var(--white)}
.breadcrumb span{color:rgba(255,255,255,0.35)}
.hero-top{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap}
.hero-badges{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.hero-badge{display:inline-block;padding:3px 12px;border-radius:20px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px}
.badge-live{background:rgba(143,205,217,.2);color:#8fcdd9}
.badge-closed{background:rgba(224,110,100,.2);color:#e8a39c}
.badge-sector{background:rgba(255,255,255,.14);color:rgba(255,255,255,.85)}
.badge-region{background:rgba(255,255,255,.14);color:rgba(255,255,255,.85)}
h1{font-family:var(--font-display);font-size:clamp(22px,3vw,30px);font-weight:600;color:var(--white);line-height:1.28;text-wrap:balance;max-width:780px}
.hero-buyer{font-size:15px;color:rgba(255,255,255,.75);margin-top:8px}
.hero-actions{display:flex;flex-direction:column;align-items:flex-end;gap:8px;flex-shrink:0}
.hero-actions .btn{white-space:nowrap}
.hero-nav{display:flex;gap:8px;font-size:12px}
.hero-nav a{color:rgba(255,255,255,.7);padding:5px 10px;border:1px solid rgba(255,255,255,.25);border-radius:6px;background:none;cursor:pointer;font-family:inherit}
.hero-nav a:hover{background:rgba(255,255,255,.1)}

.btn{display:inline-block;padding:11px 20px;border-radius:8px;font-size:13px;font-weight:700;text-align:center;border:none;cursor:pointer;font-family:inherit;text-decoration:none}
.btn-white{background:var(--white);color:var(--teal-dark)}
.btn-white:hover{background:var(--teal-light)}
.btn-outline-light{background:transparent;border:1.5px solid rgba(255,255,255,.5);color:var(--white)}
.btn-outline-light:hover{background:rgba(255,255,255,.12)}
.btn-primary{background:var(--teal-dark);color:var(--white)}
.btn-primary:hover{background:var(--teal)}
.btn-secondary{background:transparent;border:1.5px solid var(--teal-mid);color:var(--teal-dark)}
.btn-secondary:hover{background:var(--teal-light)}

/* At-a-glance row — lives inside the hero, not floating cards on top of it */
.glance{display:flex;gap:28px;flex-wrap:wrap;margin-top:18px;padding-top:18px;border-top:1px solid rgba(255,255,255,0.14)}
.gcard{display:flex;flex-direction:column;gap:2px}
.gcard .g-label{font-size:11px;font-weight:700;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:.05em}
.gcard .g-value{font-family:var(--font-display);font-size:19px;font-weight:600;color:var(--white);line-height:1.25}

.map-widget{text-align:center}
.map-widget svg{max-width:150px;margin:0 auto 6px;display:block}
.map-widget .map-cap{font-size:12px;color:var(--text-muted);font-weight:700}

/* Timeline */
.timeline-section{margin-top:28px}
.timeline-section h2{font-size:14px;font-weight:700;color:var(--steel);text-transform:uppercase;letter-spacing:.5px;margin-bottom:18px}
.timeline{display:flex;position:relative;padding-top:10px}
.timeline::before{content:"";position:absolute;top:19px;left:0;right:0;height:2px;background:var(--border)}
.tl-node{flex:1;text-align:center;position:relative;padding:0 4px}
.tl-dot{width:14px;height:14px;border-radius:50%;margin:0 auto 10px;position:relative;z-index:1;border:3px solid var(--white)}
.tl-label{font-size:11px;font-weight:700;color:var(--steel);text-transform:uppercase;letter-spacing:.3px}
.tl-date{font-family:var(--font-display);font-size:14px;font-weight:600;color:var(--text);margin-top:3px}
.tl-rel{font-size:11px;font-weight:600;margin-top:2px}

/* Main grid */
.content-grid{display:grid;grid-template-columns:1fr 320px;gap:32px;margin-top:36px;padding-bottom:48px}
.card{background:var(--white);border:1px solid var(--border);border-radius:12px;padding:22px;margin-bottom:20px}
.card h2{font-family:var(--font-display);font-size:16px;font-weight:600;color:var(--steel);margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--border)}

.kp-card{background:var(--teal-light);border:1px solid var(--border)}
.kp-card h2{border-bottom-color:var(--border)}
.kp-list{list-style:none}
.kp-list li{display:flex;gap:10px;font-size:14px;color:var(--steel);line-height:1.5;margin-bottom:10px;font-weight:500}
.kp-list li:last-child{margin-bottom:0}
.kp-list li::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--teal-mid);margin-top:7px;flex-shrink:0}

.desc-text{font-size:14px;color:var(--text-muted);line-height:1.8;white-space:pre-wrap;word-break:break-word}
.desc-toggle{background:none;border:none;color:var(--teal-mid);font-weight:700;font-size:13px;cursor:pointer;padding:10px 0 0;font-family:inherit}
.desc-full{display:none}
.desc-full.open{display:block}
.lots-extra{display:none}
.lots-extra.open{display:block}
.desc-short.hidden{display:none}

.domain-list{list-style:none}
.domain-list li{padding:6px 0}
.domain-list a{font-size:13px;color:var(--teal-mid);word-break:break-all}

.lot{background:var(--off-white);border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:8px;display:flex;justify-content:space-between;gap:10px}
.lot-title{font-size:13px;font-weight:700;color:var(--steel)}
.lot-desc{font-size:12px;color:var(--text-muted);margin-top:4px;line-height:1.6}
.lot-val{font-family:var(--font-display);font-size:14px;font-weight:600;color:var(--teal-dark);flex-shrink:0;font-variant-numeric:tabular-nums}
.doc-link{display:flex;align-items:flex-start;gap:8px;padding:9px 12px;border:1px solid var(--border);border-radius:7px;margin-bottom:6px;font-size:13px;color:var(--teal-dark);background:var(--white);word-break:break-word}
.doc-link:hover{background:var(--teal-light)}

.fact-row{display:flex;gap:16px;padding:9px 0;border-bottom:1px solid var(--border);font-size:13px}
.fact-row:last-child{border-bottom:none}
.fact-label{font-weight:600;color:var(--steel);width:110px;flex-shrink:0}
.fact-value{color:var(--text-muted);min-width:0;overflow-wrap:anywhere;word-break:break-word}

.rel-tenders{display:flex;flex-direction:column}
.rel-tender{display:flex;align-items:flex-start;gap:8px;padding:10px 0;border-bottom:1px solid var(--border);transition:background .15s;border-radius:6px}
.rel-tender:last-child{border-bottom:none}
.rel-tender:hover{background:var(--off-white)}
.rel-title{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:12.5px;font-weight:700;color:var(--steel);line-height:1.4}
.rel-meta{display:block;font-size:11px;color:var(--text-muted);margin-top:2px}
.rel-arrow{color:var(--teal-mid);font-weight:700;flex-shrink:0;margin-top:1px}
.rel-empty{font-size:12.5px;color:var(--text-muted)}

.cta-card{background:var(--steel);border-top:3px solid var(--teal-mid);border-radius:12px;padding:22px;margin-bottom:20px;text-align:center}
.cta-card h3{font-family:var(--font-display);color:var(--white);font-size:17px;font-weight:600;margin-bottom:8px}
.cta-card p{color:rgba(255,255,255,.82);font-size:13px;line-height:1.6;margin-bottom:16px}
.cta-card .btn{display:block;width:100%;margin-bottom:8px}

/* Sidebar quiz widget */
.quiz-widget{background:var(--steel);border-top:3px solid var(--teal-mid);border-radius:12px;padding:20px;margin-bottom:20px;text-align:center;transition:box-shadow .2s ease}
.quiz-widget:hover{box-shadow:0 10px 28px rgba(14,74,87,.2)}
.quiz-widget h3{font-family:var(--font-display);color:var(--white);font-size:16px;font-weight:600;margin-bottom:4px}
.quiz-widget .quiz-sub{color:rgba(255,255,255,.82);font-size:12px;margin-bottom:14px}
.quiz-widget .quiz-progress{display:flex;gap:5px;justify-content:center;margin-bottom:14px}
.quiz-widget .quiz-progress span{width:20px;height:3px;border-radius:2px;background:rgba(255,255,255,.3)}
.quiz-widget .quiz-progress span.done{background:var(--white)}
.quiz-widget .quiz-step{display:none;text-align:left}
.quiz-widget .quiz-step.active{display:block}
.quiz-widget .q-text{font-size:13px;font-weight:700;color:var(--white);margin-bottom:10px;text-align:center}
.quiz-widget .quiz-options{display:flex;flex-direction:column;gap:7px}
.quiz-widget .quiz-options button{padding:9px 12px;border:1px solid rgba(255,255,255,.35);border-radius:7px;background:rgba(255,255,255,.1);font-size:12px;font-weight:600;color:var(--white);cursor:pointer;text-align:left;font-family:inherit}
.quiz-widget .quiz-options button:hover{background:rgba(255,255,255,.22)}
.quiz-widget .quiz-result{display:none}
.quiz-widget .quiz-result.active{display:block}
.quiz-widget .score-badge{display:inline-block;background:rgba(255,255,255,.18);color:var(--white);font-weight:800;font-size:11px;padding:5px 12px;border-radius:16px;margin-bottom:10px}
.quiz-widget .quiz-result p{font-size:12px;color:rgba(255,255,255,.88);line-height:1.6;margin-bottom:14px}

.cta-banner{background:var(--steel);border-top:3px solid var(--teal-mid);padding:50px 5%;text-align:center}
.cta-banner h2{font-family:var(--font-display);font-size:26px;font-weight:600;color:var(--white);margin-bottom:8px}
.cta-banner p{font-size:14px;color:rgba(255,255,255,.8);margin-bottom:20px}

footer{background:var(--steel);color:rgba(255,255,255,.6);padding:36px 5% 24px}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px;margin-bottom:24px;max-width:1180px;margin-left:auto;margin-right:auto}
.footer-col h4{color:var(--white);font-size:14px;font-weight:700;margin-bottom:10px}
.footer-col a{display:block;font-size:13px;color:rgba(255,255,255,.55);margin-bottom:6px;transition:color .2s}
.footer-col a:hover{color:var(--white)}
.footer-bottom{border-top:1px solid rgba(255,255,255,.1);padding-top:16px;font-size:12px;display:flex;justify-content:space-between;max-width:1180px;margin:0 auto}

@media(max-width:900px){
  nav .nav-links{display:none}
  .hamburger{display:flex}
  .glance{gap:18px 28px}
  .content-grid{grid-template-columns:1fr}
  .timeline{flex-wrap:wrap;gap:16px 0}
  .tl-node{flex:0 0 50%}
  .footer-grid{grid-template-columns:1fr 1fr}
  .footer-bottom{flex-direction:column;gap:8px;text-align:center}
  .hero-actions{align-items:flex-start}
}
"""


# ── Region bucketing (ported from tender-search.html REGION_GROUPS) ────────────

REGION_GROUPS = {
    'North East England':'North East','Tees Valley and Durham':'North East','Tyne and Wear':'North East',
    'North West England':'North West','Cumbria':'North West','Greater Manchester':'North West',
    'Lancashire':'North West','Cheshire':'North West','Merseyside':'North West',
    'Yorkshire and The Humber':'Yorkshire & The Humber','East Riding and North Lincolnshire':'Yorkshire & The Humber',
    'North Yorkshire':'Yorkshire & The Humber','South Yorkshire':'Yorkshire & The Humber','West Yorkshire':'Yorkshire & The Humber',
    'East Midlands':'East Midlands','Derbyshire and Nottinghamshire':'East Midlands',
    'Leicestershire and Northamptonshire':'East Midlands','Lincolnshire':'East Midlands',
    'West Midlands':'West Midlands','Herefordshire and Worcestershire':'West Midlands','Shropshire and Staffordshire':'West Midlands',
    'East of England':'East of England','East Anglia':'East of England',
    'Bedfordshire and Hertfordshire':'East of England','Essex':'East of England',
    'London':'London','Inner London':'London','Outer London':'London',
    'South East England':'South East','Berkshire and Oxfordshire':'South East','Surrey and Sussex':'South East',
    'Hampshire and Isle of Wight':'South East','Kent':'South East',
    'South West England':'South West','Gloucestershire and Bristol':'South West','Dorset and Somerset':'South West',
    'Cornwall':'South West','Devon':'South West',
    'Wales':'Wales','West Wales':'Wales','East Wales':'Wales',
    'Scotland':'Scotland','Eastern Scotland':'Scotland','South West Scotland':'Scotland',
    'North East Scotland':'Scotland','Highlands and Islands':'Scotland',
    'Northern Ireland':'Northern Ireland',
}

def to_broad_region(specific: str) -> str:
    if not specific or specific == "UK":
        return ""
    if specific in REGION_GROUPS:
        return REGION_GROUPS[specific]
    s = specific.lower()
    if "london" in s: return "London"
    if "scotland" in s: return "Scotland"
    if "wales" in s: return "Wales"
    if "ireland" in s: return "Northern Ireland"
    return ""

_TILES = [
    ("Scotland",1,0,3),("Northern Ireland",0,1,1),("North West",1,1,1),("North East",3,1,1),
    ("Yorkshire & The Humber",2,2,2),("Wales",0,3,1),("West Midlands",1,3,1),("East Midlands",2,3,1),
    ("East of England",3,3,1),("South West",0,4,2),("London",2,4,1),("South East",3,4,1),
]
_TILE_SHORT = {"Yorkshire & The Humber":"Yorks.","Northern Ireland":"N.I.","East of England":"E.Eng.",
               "West Midlands":"W.Mid.","East Midlands":"E.Mid.","South West":"S.West","South East":"S.East",
               "North West":"N.West","North East":"N.East"}
_CELL, _GAP = 38, 4

def build_region_map_svg(broad_region: str) -> str:
    """Small schematic (non-cartographic) UK region tile grid, with the
    tender's broad region highlighted."""
    tiles = []
    for name, col, row, span in _TILES:
        x = col * (_CELL + _GAP)
        y = row * (_CELL + _GAP)
        w = span * _CELL + (span - 1) * _GAP
        h = _CELL
        active = name == broad_region
        fill = "var(--teal-mid)" if active else "var(--off-white)"
        tf = "#fff" if active else "var(--text-muted)"
        stroke = "var(--teal-dark)" if active else "var(--border)"
        short = _TILE_SHORT.get(name, name)
        tiles.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"><title>{esc(name)}</title></rect>'
            f'<text x="{x+w/2}" y="{y+h/2+3.5}" text-anchor="middle" font-size="8.5" font-weight="700" fill="{tf}">{esc(short)}</text>'
        )
    map_w = 4 * (_CELL + _GAP) - _GAP
    map_h = 5 * (_CELL + _GAP) - _GAP
    return f'<svg viewBox="0 0 {map_w} {map_h}" width="100%" height="100%">{"".join(tiles)}</svg>'


# ── Relative time / timeline ────────────────────────────────────────────────────

def _parse_dt(iso: str):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None

def human_relative(d, now) -> str:
    if d is None:
        return ""
    delta_days = (d.date() - now.date()).days
    if delta_days == 0:
        return "Today"
    ago = delta_days < 0
    n = abs(delta_days)
    if n < 14: val, unit = n, "day"
    elif n < 60: val, unit = round(n / 7), "week"
    elif n < 548: val, unit = round(n / 30.44), "month"
    else: val, unit = round(n / 365.25, 1), "year"
    val_s = f"{val:g}"
    label = f"{val_s} {unit}{'' if val == 1 else 's'}"
    return f"{label} ago" if ago else f"in {label}"

_DOT_COLOR = {"past":"var(--text-muted)","today":"var(--teal-dark)","future":"var(--teal-mid)",
              "urgent":"#c0392b","warning":"#b7670a","safe":"var(--teal-mid)","closed":"#999"}

def build_timeline_html(t: dict, now) -> str:
    published_d = _parse_dt(t.get("published",""))
    deadline_d  = _parse_dt(t.get("deadline",""))
    start_d     = _parse_dt(t.get("contractStart","")) if t.get("contractStart") else None
    end_d       = _parse_dt(t.get("contractEnd","")) if t.get("contractEnd") else None

    milestones = []
    if published_d: milestones.append(("Published", published_d, "past"))
    milestones.append(("Today", now, "today"))
    if deadline_d:
        days = days_until(t.get("deadline",""))
        kind = "closed" if (days is not None and days < 0) else deadline_class(days)
        milestones.append(("Closes", deadline_d, kind))
    if start_d: milestones.append(("Starts", start_d, "future"))
    if end_d: milestones.append(("Ends", end_d, "future"))
    milestones.sort(key=lambda m: m[1])

    nodes = []
    for label, d, kind in milestones:
        color = _DOT_COLOR.get(kind, "var(--teal-mid)")
        extra = "box-shadow:0 0 0 4px rgba(26,107,124,.15);" if kind == "today" else ""
        nodes.append(f"""
    <div class="tl-node">
      <div class="tl-dot" style="background:{color};{extra}"></div>
      <div class="tl-label">{esc(label)}</div>
      <div class="tl-date">{esc(fmt_date(d.isoformat()))}</div>
      <div class="tl-rel" style="color:{color}">{esc(human_relative(d, now))}</div>
    </div>""")
    return f'<div class="timeline">{"".join(nodes)}</div>'


# ── Rule-based key points (no AI -- built from fields we already have) ─────────

def build_key_points(t: dict, broad_region: str) -> list[str]:
    points = [esc(t.get("procedureDesc") or t.get("procedureType") or "Open procedure") + " procurement"]
    val = fmt_value(t.get("value"), t.get("currency", "GBP"))
    if val:
        points.append(f"Estimated value of {esc(val)}")
    cs, ce = _parse_dt(t.get("contractStart","")), _parse_dt(t.get("contractEnd",""))
    if cs and ce:
        months = (ce.year - cs.year) * 12 + (ce.month - cs.month)
        if months >= 12 and months % 12 == 0:
            y = months // 12
            points.append(f"Contract runs for {y} year{'s' if y > 1 else ''}")
        elif months > 0:
            points.append(f"Contract runs for {months} months")
    lots = t.get("lots", []) or []
    if len(lots) > 1:
        points.append(f"Split across {len(lots)} lots")
    if broad_region:
        points.append(f"Delivered in {esc(broad_region)}")
    if t.get("sector"):
        points.append(f"Sector: {esc(t['sector'])}")
    return points


# ── Referenced-sources / domains box ────────────────────────────────────────────

def _norm_domain(d: str) -> str:
    d = d.lower()
    return d[4:] if d.startswith("www.") else d

def build_domains(t: dict) -> list[str]:
    domains = {"find-tender.service.gov.uk"}
    email = (t.get("buyerContact") or {}).get("email", "")
    if "@" in email:
        domains.add(_norm_domain(email.split("@")[-1]))
    for doc in t.get("documents", []) or []:
        m = re.search(r"https?://([^/]+)/?", doc.get("url",""))
        if m:
            domains.add(_norm_domain(m.group(1)))
    return sorted(domains)


# ── Bid-readiness quiz widget (static -- same on every page) ───────────────────

QUIZ_WIDGET = """\
<div class="quiz-widget">
  <h3>Should You Bid on This One?</h3>
  <p class="quiz-sub">4 quick questions &rarr; your Bid Readiness Score</p>
  <div class="quiz-progress"><span id="qp1" class="done"></span><span id="qp2"></span><span id="qp3"></span><span id="qp4"></span></div>
  <div class="quiz-step active" data-step="1"><div class="q-text">Delivered a similar contract before?</div>
    <div class="quiz-options"><button onclick="quizNext(1,3)">Yes, multiple times</button><button onclick="quizNext(1,2)">Once or twice</button><button onclick="quizNext(1,0)">Not yet</button></div></div>
  <div class="quiz-step" data-step="2"><div class="q-text">Could you deliver within the timeframe?</div>
    <div class="quiz-options"><button onclick="quizNext(2,3)">Yes, comfortably</button><button onclick="quizNext(2,2)">It'd be tight</button><button onclick="quizNext(2,0)">Unsure</button></div></div>
  <div class="quiz-step" data-step="3"><div class="q-text">Written a public-sector bid before?</div>
    <div class="quiz-options"><button onclick="quizNext(3,3)">Yes, and won</button><button onclick="quizNext(3,2)">Yes, not won yet</button><button onclick="quizNext(3,0)">Never</button></div></div>
  <div class="quiz-step" data-step="4"><div class="q-text">Time to dedicate before the deadline?</div>
    <div class="quiz-options"><button onclick="quizNext(4,3)">Plenty</button><button onclick="quizNext(4,2)">Some, but tight</button><button onclick="quizNext(4,0)">Very little</button></div></div>
  <div class="quiz-result" id="quizResult">
    <div class="score-badge" id="quizScoreBadge">Bid Readiness: Strong</div>
    <p id="quizResultText"></p>
    <a href="/contact.html" class="btn btn-white" style="display:block;color:var(--teal-dark)">Get a Free Bid Consultation</a>
  </div>
</div>
<script>
let quizScore = 0;
function quizNext(step, points) {
  quizScore += points;
  document.querySelector('.quiz-step[data-step="'+step+'"]').classList.remove('active');
  const dot = document.getElementById('qp'+step); if (dot) dot.classList.add('done');
  if (step < 4) { document.querySelector('.quiz-step[data-step="'+(step+1)+'"]').classList.add('active'); return; }
  const badge = document.getElementById('quizScoreBadge'), text = document.getElementById('quizResultText');
  if (quizScore >= 9) { badge.textContent = 'Bid Readiness: Strong'; text.textContent = "You're in a good position to bid \\u2014 our bid writers can take the writing burden off your team."; }
  else if (quizScore >= 5) { badge.textContent = 'Bid Readiness: Worth a Closer Look'; text.textContent = "There are some gaps, but they're not disqualifying. A free consultation can help you decide."; }
  else { badge.textContent = 'Bid Readiness: Needs Support'; text.textContent = "This looks challenging on paper, but plenty of clients have won contracts like this. Talk to us first."; }
  document.getElementById('quizResult').classList.add('active');
}
</script>
"""


# ── Page builder ───────────────────────────────────────────────────────────────

def build_page(t: dict, slug: str, is_closed: bool, buyer_others=None, sector_related=None,
               prev_link=None, next_link=None) -> str:
    now        = datetime.now(timezone.utc)
    title_raw  = t.get("title", "UK Government Tender")
    buyer      = t.get("buyer", "")
    deadline   = t.get("deadline", "")
    value      = fmt_value(t.get("value"), t.get("currency", "GBP"))
    sector     = t.get("sector", "")
    region     = t.get("region", "")
    broad_region = to_broad_region(region)
    desc_full  = (t.get("fullDescription") or t.get("description") or "").strip()
    desc_short = desc_full[:260].rsplit(" ", 1)[0] if len(desc_full) > 260 else desc_full
    url        = t.get("url", "")
    ref        = t.get("id", "")
    procedure  = t.get("procedureDesc") or t.get("procedureType") or ""
    lots       = t.get("lots", []) or []
    documents  = t.get("documents", []) or []
    contact    = t.get("buyerContact", {}) or {}
    address    = t.get("buyerAddress", {}) or {}
    published  = fmt_date(t.get("published", ""))

    page_url   = f"{BASE_URL}/tenders/{slug}/"
    meta_desc  = meta_description(t)

    # ── Glance stat squares ────────────────────────────────────────────────────
    glance_html = f"""
<div class="glance">
  <div class="gcard"><div class="g-label">Value</div><div class="g-value">{esc(value) if value else '&mdash;'}</div></div>
  <div class="gcard"><div class="g-label">Procedure</div><div class="g-value">{esc(procedure.split()[0]) if procedure else '&mdash;'}</div></div>
  <div class="gcard"><div class="g-label">Sector</div><div class="g-value" style="font-size:13px">{esc(sector) if sector else '&mdash;'}</div></div>
  <div class="gcard"><div class="g-label">Lots</div><div class="g-value">{len(lots) or 1}</div></div>
</div>"""

    # ── Timeline ───────────────────────────────────────────────────────────────
    timeline_section = f"""
<div class="wrap timeline-section">
  <h2>Dates</h2>
  {build_timeline_html(t, now)}
</div>"""

    # ── Key points ─────────────────────────────────────────────────────────────
    key_points = build_key_points(t, broad_region)
    kp_card = f"""
<div class="card kp-card">
  <h2>Key Points</h2>
  <ul class="kp-list">{''.join(f"<li>{k}</li>" for k in key_points)}</ul>
</div>"""

    # ── Description (short + expandable) ───────────────────────────────────────
    if desc_full:
        if len(desc_full) > 260:
            desc_card = f"""
<div class="card">
  <h2>Description</h2>
  <p class="desc-text desc-short">{esc(desc_short)}&hellip;</p>
  <p class="desc-text desc-full">{esc(desc_full)}</p>
  <button class="desc-toggle" onclick="var s=this.parentElement.querySelector('.desc-short'),f=this.parentElement.querySelector('.desc-full');s.classList.toggle('hidden');f.classList.toggle('open');this.textContent=this.textContent.startsWith('Read')?'Show less':'Read full description';">Read full description</button>
</div>"""
        else:
            desc_card = f"""
<div class="card">
  <h2>Description</h2>
  <p class="desc-text">{esc(desc_full)}</p>
</div>"""
    else:
        desc_card = ""

    # ── Lots (collapsed past the first 8, same pattern as the description) ─────
    lots_card = ""
    if lots:
        def _lot_html(lot):
            lv = fmt_value(lot.get("value"), lot.get("currency", "GBP"))
            lt = esc(lot.get("title") or f"Lot {lot.get('id','')}")
            ld = esc((lot.get("description") or "")[:200])
            return f"""
<div class="lot"><div><div class="lot-title">{lt}</div>{f'<div class="lot-desc">{ld}</div>' if ld else ''}</div>{f'<div class="lot-val">{lv}</div>' if lv else ''}</div>"""
        LOTS_VISIBLE = 8
        shown_lots = "".join(_lot_html(l) for l in lots[:LOTS_VISIBLE])
        extra_lots = "".join(_lot_html(l) for l in lots[LOTS_VISIBLE:])
        lots_toggle = (
            f"""<button class="desc-toggle" onclick="var e=this.previousElementSibling,open=e.classList.toggle('open');this.textContent=open?'Show fewer lots':'Show all {len(lots)} lots';">Show all {len(lots)} lots</button>"""
            if extra_lots else ""
        )
        lots_card = f"""
<div class="card">
  <h2>Lots ({len(lots)})</h2>
  {shown_lots}
  {f'<div class="lots-extra">{extra_lots}</div>' if extra_lots else ''}
  {lots_toggle}
</div>"""

    # ── Documents ──────────────────────────────────────────────────────────────
    docs_card = ""
    if documents:
        doc_items = ""
        for doc in documents[:8]:
            doc_url = doc.get("url", "")
            doc_title = esc(doc.get("title") or doc.get("type") or "Document")
            if doc_url:
                doc_items += f'<a href="{esc(doc_url)}" target="_blank" rel="noopener" class="doc-link">{doc_title}</a>'
        if doc_items:
            docs_card = f"""
<div class="card">
  <h2>Documents &amp; Links</h2>
  {doc_items}
</div>"""

    # ── Referenced sources / domains ───────────────────────────────────────────
    domain_rows = "".join(
        f'<li><a href="https://{esc(d)}" target="_blank" rel="noopener nofollow">{esc(d)}</a></li>'
        for d in build_domains(t)
    )
    domains_card = f"""
<div class="card">
  <h2>Referenced Sources</h2>
  <ul class="domain-list">{domain_rows}</ul>
</div>"""

    main_col = f"{kp_card}{desc_card}{lots_card}{docs_card}{domains_card}"

    # ── Sidebar: quiz (open) or closed-notice CTA ──────────────────────────────
    if is_closed:
        side_cta = f"""
<div class="cta-card">
  <h3>This tender has closed</h3>
  <p>We can help you find and win similar contracts.</p>
  <a href="{CONTACT}" class="btn btn-white">Find Similar Opportunities</a>
</div>"""
    else:
        side_cta = QUIZ_WIDGET

    # ── Sidebar: region map ─────────────────────────────────────────────────────
    map_card = ""
    if broad_region:
        map_card = f"""
<div class="card map-widget">
  {build_region_map_svg(broad_region)}
  <div class="map-cap">Delivered in {esc(broad_region)}</div>
</div>"""

    # ── Sidebar: buyer card ──────────────────────────────────────────────────────
    contact_rows = ""
    if contact.get("name"):
        contact_rows += f'<div class="fact-row"><span class="fact-label">Contact</span><span class="fact-value">{esc(contact["name"])}</span></div>'
    if contact.get("email"):
        contact_rows += f'<div class="fact-row"><span class="fact-label">Email</span><span class="fact-value"><a href="mailto:{esc(contact["email"])}" style="color:var(--teal)">{esc(contact["email"])}</a></span></div>'
    if contact.get("telephone"):
        contact_rows += f'<div class="fact-row"><span class="fact-label">Phone</span><span class="fact-value">{esc(contact["telephone"])}</span></div>'
    if address.get("locality"):
        loc = esc(address.get("locality","")) + (", " + esc(address.get("postcode","")) if address.get("postcode") else "")
        contact_rows += f'<div class="fact-row"><span class="fact-label">Location</span><span class="fact-value">{loc}</span></div>'

    buyer_card = ""
    if buyer or contact_rows:
        official_btn = (
            f'<a href="{esc(url)}" target="_blank" rel="noopener" class="btn btn-secondary" style="display:block;margin-top:12px">View Official Notice</a>'
            if url else ""
        )
        buyer_card = f"""
<div class="card">
  <h2>Buyer</h2>
  {f'<div class="fact-row"><span class="fact-label">Name</span><span class="fact-value">{esc(buyer)}</span></div>' if buyer else ''}
  {contact_rows}
  {official_btn}
</div>"""

    # ── Sidebar: related tenders ─────────────────────────────────────────────────
    def _rel_rows(items):
        if not items:
            return '<p class="rel-empty">Nothing else currently listed.</p>'
        return "".join(
            f'<a class="rel-tender" href="/tenders/{esc(sl)}/"><span class="rel-arrow">&rsaquo;</span>'
            f'<span><span class="rel-title">{esc(ttl)}</span><span class="rel-meta">{esc(by)}</span></span></a>'
            for ttl, sl, by in items
        )

    buyer_card_related = ""
    if buyer_others is not None:
        buyer_card_related = f"""
<div class="card">
  <h2 style="font-size:13px">More from {esc(buyer)}</h2>
  <div class="rel-tenders">{_rel_rows(buyer_others)}</div>
</div>"""

    sector_card_related = ""
    if sector_related is not None:
        sector_card_related = f"""
<div class="card">
  <h2 style="font-size:13px">Related in {esc(sector)}</h2>
  <div class="rel-tenders">{_rel_rows(sector_related)}</div>
</div>"""

    side_col = f"{side_cta}{map_card}{buyer_card}{buyer_card_related}{sector_card_related}"

    # ── Hero badges / nav ────────────────────────────────────────────────────────
    status_badge = '<span class="hero-badge badge-closed">Closed</span>' if is_closed else '<span class="hero-badge badge-live">Live</span>'
    sector_badge = f'<span class="hero-badge badge-sector">{esc(sector)}</span>' if sector else ""
    region_badge = f'<span class="hero-badge badge-region">{esc(broad_region or region)}</span>' if (broad_region or (region and region != "UK")) else ""

    prev_html = f'<a href="/tenders/{esc(prev_link["slug"])}/">&larr; Previous</a>' if prev_link else '<span style="opacity:.4">&larr; Previous</span>'
    next_html = f'<a href="/tenders/{esc(next_link["slug"])}/">Next &rarr;</a>' if next_link else '<span style="opacity:.4">Next &rarr;</span>'

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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">
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
  <div class="hero-inner">
    <div class="breadcrumb">
      <a href="/">Home</a><span>&rsaquo;</span>
      <a href="/tender-search.html">Tender Search</a><span>&rsaquo;</span>
      <span style="color:rgba(255,255,255,0.85)">{esc(title_raw[:60])}{'…' if len(title_raw) > 60 else ''}</span>
    </div>
    <div class="hero-top">
      <div>
        <div class="hero-badges">{status_badge}{sector_badge}{region_badge}</div>
        <h1>{esc(title_raw)}</h1>
        {f'<div class="hero-buyer">{esc(buyer)}{" &middot; Published " + esc(published) if published else ""}</div>' if buyer else ''}
      </div>
      <div class="hero-actions">
        <a href="{CONTACT}" class="btn btn-white">Enquire About This Bid</a>
        <div class="hero-nav">{prev_html}{next_html}<a onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href);this.textContent='Copied!';return false;">Share</a></div>
      </div>
    </div>
    {glance_html}
  </div>
</div>

{timeline_section}

<div class="wrap content-grid">
  <div>{main_col}</div>
  <div>{side_col}</div>
</div>

<div class="cta-banner">
  <h2>Don't Miss Your Next Contract</h2>
  <p>Hawkeye Solutions helps businesses win UK public sector tenders. From bid writing to full tender management.</p>
  <a href="/contact.html" class="btn btn-white">Get a Free Consultation</a>
</div>

{FOOTER}

<script>
const ham = document.getElementById('ham');
const mob = document.getElementById('mob');
if (ham && mob) {{
  ham.addEventListener('click', () => {{
    ham.classList.toggle('open');
    mob.classList.toggle('open');
  }});
}}
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

    skipped = 0
    seen_slugs: set[str] = set()

    # ── Pass 1: assign slugs, build buyer/sector indices ───────────────────────
    entries = []  # (tender, slug, is_closed)
    buyer_index: dict[str, list[tuple[str, str, str]]] = {}
    sector_index: dict[str, list[tuple[str, str, str]]] = {}

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
        base_slug = slug
        n = 2
        while slug in seen_slugs:
            slug = f"{base_slug}-{n}"
            n += 1
        seen_slugs.add(slug)

        entries.append((t, slug, is_closed))

        row = (title, slug, t.get("buyer", ""))
        buyer = t.get("buyer", "")
        sector = t.get("sector", "")
        if buyer:
            buyer_index.setdefault(buyer, []).append(row)
        if sector:
            sector_index.setdefault(sector, []).append(row)

    # ── Pass 2: build + write each page ─────────────────────────────────────────
    generated = 0
    sitemap_entries: list[tuple[str, str]] = []

    for i, (t, slug, is_closed) in enumerate(entries):
        buyer  = t.get("buyer", "")
        sector = t.get("sector", "")

        buyer_others = [r for r in buyer_index.get(buyer, []) if r[1] != slug][:4] if buyer else []
        sector_related = [
            r for r in sector_index.get(sector, [])
            if r[1] != slug and r[2] != buyer
        ][:4] if sector else []

        prev_link = {"slug": entries[i - 1][1]} if i > 0 else None
        next_link = {"slug": entries[i + 1][1]} if i < len(entries) - 1 else None

        page_dir = out / "tenders" / slug
        page_dir.mkdir(parents=True, exist_ok=True)

        html = build_page(t, slug, is_closed, buyer_others, sector_related, prev_link, next_link)
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
