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
import shutil
from datetime import datetime, timezone, timedelta
from html import escape as esc
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_URL          = "https://hawkeye-solutions.co.uk"
CONTACT           = "/contact.html"
INPUT_FILE        = Path("uk-tenders.json")
CLEANUP_AFTER_DAYS = 30  # retire a tender's page once its deadline is this many days in the past


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
    if not amount:  # None, 0, or "" — a genuine £0 contract value isn't meaningful to show
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
    <a href="/tender-search.html" class="nav-cta"><span class="live-dot"></span>Live Tenders</a>
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
  <a href="/tender-search.html" class="mob-cta"><span class="live-dot"></span>Live Tenders</a>
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
.nav-cta{background:var(--teal-mid);color:var(--white)!important;padding:8px 18px;border-radius:6px;font-size:14px;font-weight:600!important;display:inline-flex;align-items:center}
.live-dot{display:inline-block;width:7px;height:7px;background:#2ecc71;border-radius:50%;margin-right:6px;box-shadow:0 0 0 0 rgba(46,204,113,0.7);animation:livePulse 2s infinite}
@keyframes livePulse{0%{box-shadow:0 0 0 0 rgba(46,204,113,0.7)}70%{box-shadow:0 0 0 7px rgba(46,204,113,0)}100%{box-shadow:0 0 0 0 rgba(46,204,113,0)}}
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

.who-note{background:var(--teal-light);border-radius:8px;padding:14px 16px;font-size:13px;color:var(--teal-dark);line-height:1.6;margin-bottom:14px}

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
.quiz-widget .gate-label{font-size:12px;font-weight:700;color:#fff;margin-bottom:8px;text-align:left}

/* ---- The payoff overlay: appears once the email's been given, sized for
   its own moment rather than squeezed into the 320px sidebar ---- */
.rc-overlay{position:fixed;inset:0;background:rgba(10,20,25,.6);backdrop-filter:blur(2px);z-index:500;display:flex;align-items:center;justify-content:center;padding:24px;animation:rcFadeIn .18s ease}
@keyframes rcFadeIn{from{opacity:0}to{opacity:1}}
.rc-overlay-inner{position:relative;width:100%;max-width:440px;animation:rcPopIn .22s cubic-bezier(.2,.8,.2,1)}
@keyframes rcPopIn{from{opacity:0;transform:translateY(10px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
.rc-close{position:absolute;top:-14px;right:-14px;width:32px;height:32px;border-radius:50%;background:var(--white);border:1px solid var(--border);color:var(--steel);font-size:18px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:2}
.rc-close:hover{background:var(--off-white)}

/* ---- Bid Readiness Card reveal (strong / worth a closer look) ---- */
.rc-card{background:var(--off-white);border-radius:18px;overflow:hidden;text-align:left;box-shadow:0 24px 60px -20px rgba(0,0,0,.5)}
.rc-head{background:var(--steel);padding:30px 30px 0;position:relative}
.rc-head::before{content:'';position:absolute;top:-30%;right:-14%;width:240px;height:240px;background:url('/logo.png') no-repeat center/contain;opacity:.09;filter:grayscale(1) brightness(2.4);pointer-events:none}
.rc-brand{display:flex;align-items:center;gap:8px;margin-bottom:20px;position:relative;z-index:1}
.rc-brand .dot{width:7px;height:7px;border-radius:50%;background:#2ecc71}
.rc-brand span{font-family:var(--font-display);font-size:14px;font-weight:600;color:rgba(255,255,255,.9)}
.rc-eyebrow{font-size:11px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:rgba(255,255,255,.5);margin-bottom:7px;position:relative;z-index:1}
.rc-score{font-family:var(--font-display);font-size:30px;font-weight:700;color:#fff;margin-bottom:3px;position:relative;z-index:1}
.rc-score-sub{font-size:13px;color:rgba(255,255,255,.6);margin-bottom:22px;position:relative;z-index:1}
.rc-title{font-family:var(--font-display);font-size:19px;font-weight:600;color:#fff;line-height:1.35;margin-bottom:14px;position:relative;z-index:1}
.rc-chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:20px;position:relative;z-index:1}
.rc-chip{font-size:12px;font-weight:600;color:rgba(255,255,255,.85);background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.14);border-radius:20px;padding:4px 11px}
.rc-stats{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:rgba(255,255,255,.1);border-radius:10px;overflow:hidden;margin-bottom:26px;position:relative;z-index:1}
.rc-stat{background:rgba(255,255,255,.04);padding:13px 16px}
.rc-stat-label{font-size:10px;font-weight:700;letter-spacing:.3px;text-transform:uppercase;color:rgba(255,255,255,.45);margin-bottom:3px}
.rc-stat-val{font-family:var(--font-display);font-size:17px;font-weight:600;color:#fff}
.rc-foot{padding:20px 30px 26px;background:var(--white)}
.rc-foot-text{font-size:13.5px;color:var(--text-muted)!important;line-height:1.65;margin:0}

/* ---- Weak-score reveal: a note, not a trophy ---- */
.rc-note{background:var(--steel);border-radius:18px;padding:28px 30px 30px;text-align:left;box-shadow:0 24px 60px -20px rgba(0,0,0,.5)}
.rc-note strong{display:block;color:#fff;font-family:var(--font-display);font-size:17px;font-weight:600;margin-bottom:10px}
.rc-note-text{color:rgba(255,255,255,.82)!important;font-size:14px;line-height:1.75;margin:0}

@media(max-width:480px){
  .rc-overlay{padding:16px}
  .rc-head{padding:24px 22px 0}
  .rc-foot{padding:16px 22px 22px}
  .rc-note{padding:22px}
  .rc-score{font-size:26px}
}

.cta-banner{background:var(--steel);border-top:3px solid var(--teal-mid);padding:50px 5%;text-align:center}
.cta-banner h2{font-family:var(--font-display);font-size:26px;font-weight:600;color:var(--white);margin-bottom:8px}
.cta-banner p{font-size:14px;color:rgba(255,255,255,.8);margin-bottom:20px}

footer{background:var(--steel);color:rgba(255,255,255,.6);padding:36px 5% 24px}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px;margin-bottom:24px;max-width:1180px;margin-left:auto;margin-right:auto}
.footer-col h4{color:var(--white);font-size:14px;font-weight:700;margin-bottom:10px}
.footer-col a{display:block;font-size:13px;color:rgba(255,255,255,.55);margin-bottom:6px;transition:color .2s}
.footer-col a:hover{color:var(--white)}
.footer-bottom{border-top:1px solid rgba(255,255,255,.1);padding-top:16px;font-size:12px;display:flex;justify-content:space-between;max-width:1180px;margin:0 auto}

/* ── Hub pages (sector / region tender listings) ── */
.hub-intro{font-size:14.5px;color:var(--text-muted);line-height:1.8;max-width:760px;margin-bottom:8px}
.hub-count{font-size:13px;color:rgba(255,255,255,.6);margin-top:10px}
.hub-wrap{max-width:1180px;margin:0 auto;padding:36px 5% 56px}
.hub-nav-links{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:30px}
.hub-nav-pill{font-size:12.5px;font-weight:600;color:var(--teal-dark);background:var(--teal-light);border:1px solid var(--border);border-radius:20px;padding:6px 14px;transition:background .15s}
.hub-nav-pill:hover{background:#d9eef3}
.hub-nav-pill.active{background:var(--teal-dark);color:var(--white)}
.hub-list{display:flex;flex-direction:column;border-top:1px solid var(--border)}
.hub-row{display:flex;gap:18px;align-items:center;padding:16px 4px;border-bottom:1px solid var(--border);transition:background .15s}
.hub-row:hover{background:var(--off-white)}
.hub-row-main{flex:1;min-width:0}
.hub-row-title{font-size:14.5px;font-weight:700;color:var(--steel);line-height:1.4;display:block;margin-bottom:3px}
.hub-row-meta{font-size:12.5px;color:var(--text-muted)}
.hub-row-side{flex-shrink:0;display:flex;align-items:center;gap:16px;text-align:right}
.hub-row-value{font-family:var(--font-display);font-size:14.5px;font-weight:600;color:var(--teal-dark);white-space:nowrap}
.hub-row-deadline{font-size:12px;font-weight:700;white-space:nowrap}
.hub-row-deadline.urgent{color:var(--urgent)}
.hub-row-deadline.warning{color:var(--warning)}
.hub-row-deadline.safe{color:var(--safe)}
.hub-empty{padding:40px 0;text-align:center;color:var(--text-muted);font-size:14px}
.hub-empty a{color:var(--teal-mid);font-weight:600}

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
  .hub-row{flex-direction:column;align-items:flex-start;gap:6px}
  .hub-row-side{width:100%;justify-content:space-between}
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

BROAD_REGION_ORDER = [
    "North East", "North West", "Yorkshire & The Humber",
    "East Midlands", "West Midlands", "East of England",
    "London", "South East", "South West",
    "Wales", "Scotland", "Northern Ireland",
]


# ── Marketed-sector hubs ─────────────────────────────────────────────────────
# Hawkeye markets itself around a specific set of sectors (see sectors.html),
# not the raw ~43-category CPV taxonomy the pipeline tags each tender with.
# This maps the raw `sector` field into those marketed sectors so hub pages
# stay aligned with the business's actual positioning rather than exposing
# thin pages for categories (Mining, Chemicals, ...) that aren't a specialism.

MARKETED_SECTORS = [
    {"key": "recruitment", "name": "Recruitment & Staffing",
     "intro": "Public sector recruitment tendering is one of the most competitive landscapes in UK procurement. Browse live opportunities across temporary and permanent recruitment, managed service contracts, executive search and neutral vendor frameworks."},
    {"key": "it", "name": "IT Consultancy & Technology",
     "intro": "The public sector is one of the UK's largest buyers of technology consultancy. Browse live opportunities across G-Cloud, DOS 7, Crown Commercial Service and Digital Marketplace routes."},
    {"key": "utilities", "name": "Utilities & Energy",
     "intro": "Utilities buyers run some of the most demanding procurement processes in the UK, with complex supply chain requirements and multi-year contract values. Browse live opportunities across water, gas, electricity and environmental services."},
    {"key": "nhs", "name": "NHS & Health",
     "intro": "The NHS is one of the most active public sector procurement bodies in the UK. Browse live opportunities across workforce frameworks, medical supplies, laboratory services and health technology."},
    {"key": "councils", "name": "Local Government & Councils",
     "intro": "Local authorities are prolific buyers of professional services and operational support. Browse live public administration opportunities from councils across England."},
    {"key": "construction", "name": "Construction & Infrastructure",
     "intro": "Construction and infrastructure tendering spans major capital programmes, built environment contracts and specialist consultancy. Browse live opportunities across construction works, architecture & engineering and construction materials."},
    {"key": "events", "name": "Events & Hospitality",
     "intro": "Events and hospitality tendering requires demonstrating operational delivery, logistics management and compliance at scale. Browse live opportunities across event management, hospitality and venue services."},
]
MARKETED_SECTOR_BY_KEY = {s["key"]: s for s in MARKETED_SECTORS}

MARKETED_SECTOR_MAP = {
    "Recruitment & Staffing": "recruitment",
    "IT Services": "it", "IT Consultancy": "it", "Software": "it", "IT Hardware": "it",
    "Energy": "utilities", "Environmental Services": "utilities",
    "Health & Social Care": "nhs", "Medical Supplies": "nhs", "Laboratory Equipment": "nhs",
    "Public Administration": "councils",
    "Construction Works": "construction", "Construction Materials": "construction",
    "Architecture & Engineering": "construction", "Works": "construction", "Industrial Machinery": "construction",
    "Events & Conferences": "events", "Hospitality": "events", "Recreation & Culture": "events",
}

def to_marketed_sector(raw_sector: str) -> str:
    """Raw CPV sector -> marketed sector key, or '' if it doesn't map to one
    of Hawkeye's marketed specialisms."""
    return MARKETED_SECTOR_MAP.get(raw_sector, "")

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


# ── Scope & eligibility card (award criteria, procedure, who can bid) ──────────

# Real PCR2015/OJEU procedure classifications -- each has a distinct, well-
# defined answer to "can I just submit a bid, or is there a gate first".
# Only "open" and "selective" show up in the live dataset today, but "limited"
# and "direct" are kept for completeness since they're valid OCDS values.
PROCEDURE_ELIGIBILITY = {
    "open":      "Open procedure — any supplier can submit a full tender directly. There is no pre-qualification stage to pass first.",
    "selective": "Restricted procedure — suppliers must pass a pre-qualification (PQQ/SQ) stage before being invited to submit a full tender. You cannot submit a bid outright.",
    "limited":   "Negotiated procedure — the buyer selects and negotiates with suppliers directly, typically after an initial evaluation stage.",
    "direct":    "Direct award — the buyer has awarded this contract directly, without running a competitive tender.",
}

def build_details_card(t: dict, procedure: str) -> str:
    """Surfaces the scope/eligibility facts that already exist in the scraped
    data (award criteria, procedure type, CPV code) but weren't being shown
    anywhere on the standalone tender page -- only used internally for the
    quiz widget's personalisation. Mirrors the 'Tender Details' block already
    shown in the search page's drawer, so the two stay consistent."""
    award_text = (t.get("awardCriteriaDesc") or "").strip()
    proc_type  = (t.get("procedureType") or "").strip().lower()
    eligibility = PROCEDURE_ELIGIBILITY.get(proc_type, "")
    cpv = t.get("cpvCode") or ""

    if not (award_text or procedure or eligibility or cpv):
        return ""

    rows = ""
    if procedure:
        rows += f'<div class="fact-row"><span class="fact-label">Procedure</span><span class="fact-value">{esc(procedure)}</span></div>'
    if award_text:
        rows += f'<div class="fact-row"><span class="fact-label">Award Criteria</span><span class="fact-value">{esc(award_text)}</span></div>'
    if cpv:
        rows += f'<div class="fact-row"><span class="fact-label">CPV Code</span><span class="fact-value">{esc(cpv)}</span></div>'

    return f"""
<div class="card">
  <h2>Scope &amp; Who Can Bid</h2>
  {f'<div class="who-note">{eligibility}</div>' if eligibility else ''}
  {rows}
</div>"""


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

def build_domains(t: dict) -> list[tuple[str, str]]:
    """(domain, link) pairs -- each domain links to the actual page it was
    found on, not just its homepage (e.g. Find a Tender links to this
    specific notice, not the site root)."""
    ft_domain = "find-tender.service.gov.uk"
    official_url = t.get("url", "")
    entries: dict[str, str] = {ft_domain: official_url or f"https://{ft_domain}"}

    email = (t.get("buyerContact") or {}).get("email", "")
    if "@" in email:
        d = _norm_domain(email.split("@")[-1])
        entries.setdefault(d, f"https://{d}")

    for doc in t.get("documents", []) or []:
        doc_url = doc.get("url", "")
        m = re.search(r"https?://([^/]+)/?", doc_url)
        if m:
            d = _norm_domain(m.group(1))
            if d not in entries or entries[d] == f"https://{d}":
                entries[d] = doc_url

    return sorted(entries.items())


# ── Bid-readiness quiz widget (static -- same on every page) ───────────────────

def build_quiz_widget(t: dict, slug: str, value_str: str, sector: str) -> str:
    """Bid-readiness quiz, personalised to this specific tender's own facts
    (award criteria split, days left) and to whichever answer was weakest,
    then captures the visitor's email as a CRM lead via a Netlify Function."""
    title_raw = t.get("title", "this tender")
    days_left = days_until(t.get("deadline", ""))
    award_text = (t.get("awardCriteriaDesc") or "").strip()
    # Only worth quoting back if it's short and looks like an actual scoring
    # split (e.g. "70% quality and 30% price") -- not a wall of regulatory text
    score_split = award_text if (award_text and len(award_text) <= 160 and "%" in award_text) else ""

    context = {
        "title": title_raw,
        "slug": slug,
        "value": value_str or "",
        "rawValue": t.get("value"),  # raw number, not the "£100m"-style string -- CRM pipeline math needs a real number
        "sector": sector or "",
        "daysLeft": days_left,
        "scoreSplit": score_split,
    }
    context_json = json.dumps(context, ensure_ascii=False)

    return f"""\
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

    <div id="quizGate">
      <p class="gate-label" id="quizGateLabel">Want your personalised Bid Readiness Card?</p>
      <form id="quizEmailForm" onsubmit="return submitQuizLead(event)">
        <input type="text" id="quizBotField" name="company" autocomplete="off" tabindex="-1" style="position:absolute;opacity:0;height:0;width:0;pointer-events:none" aria-hidden="true">
        <input type="email" id="quizEmail" placeholder="you@company.com" required
          style="width:100%;padding:10px 12px;border-radius:7px;border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.1);color:#fff;font-family:inherit;font-size:13px;margin-bottom:8px;box-sizing:border-box">
        <button type="submit" id="quizSubmitBtn" class="btn btn-white" style="display:block;width:100%;color:var(--teal-dark)">Email me my result</button>
        <p id="quizEmailNote" style="font-size:11px;color:rgba(255,255,255,.6);margin-top:6px;min-height:14px"></p>
      </form>
    </div>

    <!-- Small, permanent confirmation left in the sidebar once the overlay has been seen -->
    <div id="quizSentNote" style="display:none;text-align:left;background:rgba(255,255,255,.08);border-radius:8px;padding:12px 14px">
      <p style="font-size:12px;color:rgba(255,255,255,.8);margin:0;line-height:1.5">&#10003; Got it. <a href="#" id="quizReopenLink" style="color:#fff;font-weight:700;text-decoration:underline">View it again</a></p>
    </div>
  </div>
</div>

<!-- The payoff moment: a centered overlay, not boxed into the sidebar's width -->
<div id="rcOverlay" class="rc-overlay" style="display:none">
  <div class="rc-overlay-inner">
    <button type="button" class="rc-close" id="rcClose" aria-label="Close">&times;</button>

    <!-- Strong / Worth a Closer Look -->
    <div id="rcCard" class="rc-card" style="display:none">
      <div class="rc-head">
        <div class="rc-brand"><span class="dot"></span><span>Hawkeye Solutions</span></div>
        <div class="rc-eyebrow">Bid Readiness Score</div>
        <div class="rc-score" id="rcScoreWord">Strong</div>
        <div class="rc-score-sub" id="rcScoreSub">9 / 12 points</div>
        <div class="rc-title" id="rcTitle"></div>
        <div class="rc-chips" id="rcChips"></div>
        <div class="rc-stats" id="rcStats"></div>
      </div>
      <div class="rc-foot">
        <p class="rc-foot-text">This has been logged against your details. If anything here is worth a conversation, just get in touch, we read every message personally.</p>
      </div>
    </div>

    <!-- Needs Support -- a note, not a score -->
    <div id="rcNote" class="rc-note" style="display:none">
      <strong>Thanks &mdash; that's genuinely useful context.</strong>
      <p class="rc-note-text" id="rcNoteText"></p>
    </div>
  </div>
</div>
<script>
(function() {{
  var QUIZ_CTX = {context_json};
  var quizAnswers = [];

  window.quizNext = function(step, points) {{
    quizAnswers.push({{step: step, points: points}});
    document.querySelector('.quiz-step[data-step="'+step+'"]').classList.remove('active');
    var dot = document.getElementById('qp'+step); if (dot) dot.classList.add('done');
    if (step < 4) {{ document.querySelector('.quiz-step[data-step="'+(step+1)+'"]').classList.add('active'); return; }}
    showQuizResult();
  }};

  function showQuizResult() {{
    var total = quizAnswers.reduce(function(s,a){{ return s+a.points; }}, 0);
    var weakest = quizAnswers.reduce(function(m,a){{ return a.points < m.points ? a : m; }}, quizAnswers[0]);
    var SERVICES = {{
      1: {{name:'Bid Writing', why:"translating your real experience into evaluator-ready evidence"}},
      3: {{name:'Bid Writing', why:"writing the submission itself, so inexperience with public-sector bids isn't the blocker"}},
      2: {{name:'Bid Management', why:"tracking every deadline and milestone so nothing slips"}},
      4: {{name:'Bid Management', why:"running the process so it doesn't eat your week"}}
    }};
    var service = SERVICES[weakest.step];
    var tier, badge;
    if (total >= 9) {{ tier = 'Strong'; badge = 'Bid Readiness: Strong'; }}
    else if (total >= 5) {{ tier = 'Worth a Closer Look'; badge = 'Bid Readiness: Worth a Closer Look'; }}
    else {{ tier = 'Needs Support'; badge = 'Bid Readiness: Needs Support'; }}

    var msg;
    if (tier === 'Strong') {{ msg = "You're in a strong position on " + QUIZ_CTX.title + ". "; }}
    else if (tier === 'Worth a Closer Look') {{ msg = "There are a couple of gaps on " + QUIZ_CTX.title + ", but nothing disqualifying. "; }}
    else {{ msg = QUIZ_CTX.title + " looks like a stretch on paper, but plenty of clients have won contracts like this. "; }}
    msg += "The thing most worth sorting first is " + service.why + ".";
    if (QUIZ_CTX.scoreSplit) {{ msg += " Worth knowing: this one is scored " + QUIZ_CTX.scoreSplit.replace(/\\.$/, '') + ", so that's where the marks are."; }}
    if (QUIZ_CTX.daysLeft !== null && QUIZ_CTX.daysLeft >= 0 && QUIZ_CTX.daysLeft <= 10) {{
      msg += " With " + QUIZ_CTX.daysLeft + " day" + (QUIZ_CTX.daysLeft === 1 ? '' : 's') + " left, speed matters more than perfection right now.";
    }}

    document.getElementById('quizScoreBadge').textContent = badge;
    document.getElementById('quizResultText').textContent = msg;
    document.getElementById('quizResult').classList.add('active');

    // The ask after the free result changes with the tier -- a card is
    // something worth keeping, so it's only offered when the score actually
    // earns it. A weak score gets a straight, specific note instead.
    var gateLabel = document.getElementById('quizGateLabel');
    gateLabel.textContent = (tier === 'Needs Support')
      ? 'Want the specific breakdown of what to fix first?'
      : 'Want your personalised Bid Readiness Card?';

    var noteText;
    if (tier === 'Strong') {{
      noteText = "Based on your answers, " + QUIZ_CTX.title + " plays to real strengths you already have. The main thing left is " + service.why + ", nothing more fundamental than that.";
    }} else if (tier === 'Worth a Closer Look') {{
      noteText = "Nothing here rules you out of " + QUIZ_CTX.title + ", but " + service.why + " is the gap most likely to cost marks if it's left unaddressed.";
    }} else {{
      noteText = "The honest read on " + QUIZ_CTX.title + " is that " + service.why + " is the real gap, not your fit for the work itself. That's exactly the kind of thing we help close, often faster than people expect.";
    }}

    window.__quizLead = {{
      total: total, scoreTier: tier, weakestStep: weakest.step,
      recommendedService: service.name, answers: quizAnswers, noteText: noteText
    }};
  }}

  function openOverlay() {{
    document.getElementById('rcOverlay').style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }}
  function closeOverlay() {{
    document.getElementById('rcOverlay').style.display = 'none';
    document.body.style.overflow = '';
  }}
  window.addEventListener('keydown', function(e) {{ if (e.key === 'Escape') closeOverlay(); }});

  function revealResult() {{
    var lead = window.__quizLead || {{}};
    document.getElementById('quizGate').style.display = 'none';
    document.getElementById('quizSentNote').style.display = 'block';

    if (lead.scoreTier === 'Needs Support') {{
      document.getElementById('rcNoteText').textContent = lead.noteText || '';
      document.getElementById('rcNote').style.display = 'block';
      openOverlay();
      return;
    }}

    var scoreWord = lead.scoreTier === 'Strong' ? 'Strong' : 'Worth a Closer Look';
    document.getElementById('rcScoreWord').textContent = scoreWord;
    document.getElementById('rcScoreSub').textContent = lead.total + ' / 12 points';
    document.getElementById('rcTitle').textContent = QUIZ_CTX.title;

    var chips = document.getElementById('rcChips');
    chips.innerHTML = '';
    if (QUIZ_CTX.sector) chips.innerHTML += '<span class="rc-chip">' + QUIZ_CTX.sector + '</span>';

    var stats = document.getElementById('rcStats');
    stats.innerHTML =
      '<div class="rc-stat"><div class="rc-stat-label">Est. Value</div><div class="rc-stat-val">' + (QUIZ_CTX.value || 'Not stated') + '</div></div>' +
      '<div class="rc-stat"><div class="rc-stat-label">Closes In</div><div class="rc-stat-val">' + (QUIZ_CTX.daysLeft != null ? QUIZ_CTX.daysLeft + ' days' : '\\u2014') + '</div></div>';

    document.getElementById('rcCard').style.display = 'block';
    openOverlay();
  }}

  document.getElementById('rcClose').addEventListener('click', closeOverlay);
  document.getElementById('rcOverlay').addEventListener('click', function(e) {{
    if (e.target.id === 'rcOverlay') closeOverlay();
  }});
  document.getElementById('quizReopenLink').addEventListener('click', function(e) {{
    e.preventDefault();
    openOverlay();
  }});

  window.submitQuizLead = function(e) {{
    e.preventDefault();
    var email = document.getElementById('quizEmail').value.trim();
    var bot = document.getElementById('quizBotField').value;
    var btn = document.getElementById('quizSubmitBtn');
    var note = document.getElementById('quizEmailNote');
    if (bot) return false;
    if (!email || email.indexOf('@') === -1) {{ note.textContent = 'Enter a valid email.'; note.style.color = '#f08080'; return false; }}
    btn.disabled = true; btn.textContent = 'Sending\\u2026';
    var lead = window.__quizLead || {{}};
    fetch('/.netlify/functions/quiz-lead', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        email: email,
        tenderTitle: QUIZ_CTX.title,
        tenderSlug: QUIZ_CTX.slug,
        tenderUrl: location.href,
        sector: QUIZ_CTX.sector,
        value: QUIZ_CTX.value,
        rawValue: QUIZ_CTX.rawValue,
        score: lead.total,
        scoreTier: lead.scoreTier,
        weakestStep: lead.weakestStep,
        recommendedService: lead.recommendedService,
        answers: lead.answers,
        botField: bot
      }})
    }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
      if (data && data.ok) {{
        revealResult();
      }} else {{
        note.textContent = 'Something went wrong \\u2014 try again, or email info@hawkeye-solutions.co.uk directly.';
        note.style.color = '#f08080';
        btn.disabled = false; btn.textContent = 'Email me my result';
      }}
    }}).catch(function() {{
      note.textContent = 'Something went wrong \\u2014 try again, or email info@hawkeye-solutions.co.uk directly.';
      note.style.color = '#f08080';
      btn.disabled = false; btn.textContent = 'Email me my result';
    }});
    return false;
  }};
}})();
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
        f'<li><a href="{esc(link)}" target="_blank" rel="noopener nofollow">{esc(d)}</a></li>'
        for d, link in build_domains(t)
    )
    domains_card = f"""
<div class="card">
  <h2>Referenced Sources</h2>
  <ul class="domain-list">{domain_rows}</ul>
</div>"""

    details_card = build_details_card(t, procedure)
    main_col = f"{kp_card}{desc_card}{details_card}{lots_card}{docs_card}{domains_card}"

    # ── Sidebar: quiz (open) or closed-notice CTA ──────────────────────────────
    if is_closed:
        side_cta = f"""
<div class="cta-card">
  <h3>This tender has closed</h3>
  <p>We can help you find and win similar contracts.</p>
  <a href="{CONTACT}" class="btn btn-white">Find Similar Opportunities</a>
</div>"""
    else:
        side_cta = build_quiz_widget(t, slug, value, sector)

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
        marketed_key = to_marketed_sector(sector)
        view_all_link = (
            f'<a href="/tenders/sector/{marketed_key}/" style="display:block;margin-top:10px;font-size:12.5px;font-weight:700;color:var(--teal-mid)">View all {esc(MARKETED_SECTOR_BY_KEY[marketed_key]["name"])} tenders &rarr;</a>'
            if marketed_key else ""
        )
        sector_card_related = f"""
<div class="card">
  <h2 style="font-size:13px">Related in {esc(sector)}</h2>
  <div class="rel-tenders">{_rel_rows(sector_related)}</div>
  {view_all_link}
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
<meta property="og:site_name" content="Hawkeye Solutions">
<meta property="og:image" content="{BASE_URL}/logo.png">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{esc(title_raw)}">
<meta name="twitter:description" content="{esc(meta_desc)}">
<meta name="twitter:image" content="{BASE_URL}/logo.png">
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




# ── Hub pages (sector / region tender listings) ─────────────────────────────

def build_hub_row(row: dict) -> str:
    days = days_until(row.get("deadline", ""))
    dl_class = deadline_class(days)
    dl_label = (
        "Deadline passed" if days is not None and days < 0 else
        "Closes today" if days == 0 else
        "1 day left" if days == 1 else
        f"{days} days left" if days is not None else "Open deadline"
    )
    val = fmt_value(row.get("value"), row.get("currency", "GBP"))
    meta_bits = [row.get("buyer", "")]
    if row.get("location"):
        meta_bits.append(row["location"])
    meta = " &middot; ".join(esc(b) for b in meta_bits if b)
    return f"""\
<a class="hub-row" href="/tenders/{esc(row['slug'])}/">
  <div class="hub-row-main">
    <span class="hub-row-title">{esc(row['title'])}</span>
    <span class="hub-row-meta">{meta}</span>
  </div>
  <div class="hub-row-side">
    {f'<span class="hub-row-value">{esc(val)}</span>' if val else ''}
    <span class="hub-row-deadline {dl_class}">{esc(dl_label)}</span>
  </div>
</a>"""


def build_hub_page(hub_type: str, slug: str, name: str, intro: str, rows: list[dict],
                    sibling_links: list[tuple[str, str]]) -> str:
    """hub_type: 'sector' or 'region'. sibling_links: [(name, slug), ...] for
    the other hubs of the same type, rendered as a cross-link pill row."""
    page_url = f"{BASE_URL}/tenders/{hub_type}/{slug}/"
    crumb_label = "Sector" if hub_type == "sector" else "Region"
    title = f"{name} Tenders | UK Public Sector {crumb_label} Hub | Hawkeye Solutions"
    if len(title) > 65:
        title = f"{name} Tenders | Hawkeye Solutions"
    meta_desc = f"{len(rows)} live UK public sector {name} tender{'s' if len(rows) != 1 else ''} — updated daily. {intro}"[:300]

    rows_sorted = sorted(rows, key=lambda r: (r.get("deadline") or "9999"))
    list_html = (
        "".join(build_hub_row(r) for r in rows_sorted)
        if rows_sorted else
        f'<div class="hub-empty">No live {esc(name)} tenders right now &mdash; <a href="{CONTACT}">get in touch</a> and we will help you find the right opportunity, or check back soon.</div>'
    )

    sibling_type_label = "sector" if hub_type == "sector" else "region"
    siblings_html = "".join(
        f'<a class="hub-nav-pill" href="/tenders/{hub_type}/{s_slug}/">{esc(s_name)}</a>'
        for s_name, s_slug in sibling_links
    )

    jsonld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": meta_desc,
        "url": page_url,
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": BASE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "Tender Search", "item": BASE_URL + "/tender-search.html"},
                {"@type": "ListItem", "position": 3, "name": name, "item": page_url},
            ],
        },
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(rows_sorted),
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "url": f"{BASE_URL}/tenders/{r['slug']}/"}
                for i, r in enumerate(rows_sorted[:50])
            ],
        },
    }

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(meta_desc)}">
<link rel="canonical" href="{esc(page_url)}">
<link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96">
<link rel="shortcut icon" href="/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Hawkeye Solutions">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(meta_desc)}">
<meta property="og:url" content="{esc(page_url)}">
<meta property="og:image" content="{BASE_URL}/logo.png">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(meta_desc)}">
<meta name="twitter:image" content="{BASE_URL}/logo.png">
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
      <span style="color:rgba(255,255,255,0.85)">{esc(name)}</span>
    </div>
    <h1>{esc(name)} Tenders</h1>
    <div class="hub-count">{len(rows_sorted)} live opportunit{'y' if len(rows_sorted) == 1 else 'ies'} &middot; updated daily</div>
  </div>
</div>

<div class="hub-wrap">
  <p class="hub-intro" style="margin:28px 0 24px">{esc(intro)}</p>
  <div class="hub-list">{list_html}</div>
  {f'<div class="hub-nav-links" style="margin-top:36px"><span style="font-size:12.5px;font-weight:700;color:var(--steel);width:100%;margin-bottom:6px">Browse other {sibling_type_label}s</span>{siblings_html}</div>' if siblings_html else ''}
</div>

<div class="cta-banner">
  <h2>Found a {esc(name)} Tender You Want to Win?</h2>
  <p>Hawkeye Solutions specialises in {esc(name.lower())} bid writing, with an 85%+ success rate across public sector contracts.</p>
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

def build_sitemap(entries: list[tuple[str, str, str, str]]) -> str:
    """entries: (url_path relative to BASE_URL, lastmod, changefreq, priority)"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls  = "\n".join(
        f"  <url>\n"
        f"    <loc>{BASE_URL}/{path}</loc>\n"
        f"    <lastmod>{lastmod or today}</lastmod>\n"
        f"    <changefreq>{changefreq}</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        f"  </url>"
        for path, lastmod, changefreq, priority in entries
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
    cleanup_cutoff = now - timedelta(days=CLEANUP_AFTER_DAYS)

    skipped = 0
    retired = 0
    seen_slugs: set[str] = set()

    # ── Pass 1: assign slugs, build buyer/sector indices ───────────────────────
    entries = []  # (tender, slug, is_closed)
    buyer_index: dict[str, list[tuple[str, str, str]]] = {}
    sector_index: dict[str, list[tuple[str, str, str]]] = {}
    marketed_sector_index: dict[str, list[dict]] = {}
    region_index: dict[str, list[dict]] = {}

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
                # A tender whose deadline is more than CLEANUP_AFTER_DAYS in the
                # past is retired: don't (re)generate its page, and let the
                # cleanup pass below remove it from disk if it already exists.
                if dl < cleanup_cutoff:
                    retired += 1
                    continue
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

        # Hub indices only take genuinely live tenders — a sector/region hub
        # is meant to showcase current opportunities, not ones past deadline.
        if not is_closed:
            broad_region = to_broad_region(t.get("region", ""))
            hub_row = {
                "title": title, "slug": slug, "buyer": buyer,
                "deadline": deadline, "value": t.get("value"), "currency": t.get("currency", "GBP"),
                "location": broad_region or (t.get("region", "") if t.get("region", "") not in ("", "UK") else ""),
            }
            marketed_key = to_marketed_sector(sector)
            if marketed_key:
                marketed_sector_index.setdefault(marketed_key, []).append(hub_row)
            if broad_region:
                region_index.setdefault(broad_region, []).append(hub_row)

    # ── Pass 2: build + write each page ─────────────────────────────────────────
    generated = 0
    sitemap_entries: list[tuple[str, str, str, str]] = []

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
        sitemap_entries.append((f"tenders/{slug}/", published, "weekly", "0.7"))
        generated += 1

    # ── Pass 2.5: build sector / region hub pages ───────────────────────────────
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hubs_generated = 0

    for ms in MARKETED_SECTORS:
        key, name, intro = ms["key"], ms["name"], ms["intro"]
        rows = marketed_sector_index.get(key, [])
        siblings = [(o["name"], o["key"]) for o in MARKETED_SECTORS if o["key"] != key]
        hub_dir = out / "tenders" / "sector" / key
        hub_dir.mkdir(parents=True, exist_ok=True)
        html = build_hub_page("sector", key, name, intro, rows, siblings)
        (hub_dir / "index.html").write_text(html, encoding="utf-8")
        sitemap_entries.append((f"tenders/sector/{key}/", today_str, "daily", "0.6"))
        hubs_generated += 1

    for region_name in BROAD_REGION_ORDER:
        region_key = slugify(region_name)
        rows = region_index.get(region_name, [])
        siblings = [(r, slugify(r)) for r in BROAD_REGION_ORDER if r != region_name]
        hub_dir = out / "tenders" / "region" / region_key
        hub_dir.mkdir(parents=True, exist_ok=True)
        intro = f"Live UK public sector tenders based in {region_name}, across all sectors, updated daily from Find a Tender."
        html = build_hub_page("region", region_key, region_name, intro, rows, siblings)
        (hub_dir / "index.html").write_text(html, encoding="utf-8")
        sitemap_entries.append((f"tenders/region/{region_key}/", today_str, "daily", "0.6"))
        hubs_generated += 1

    # Write sitemap
    sitemap_path = out / "sitemap.xml"
    sitemap_path.write_text(build_sitemap(sitemap_entries), encoding="utf-8")

    # ── Pass 3: clean up retired tender pages still sitting on disk ────────────
    # A directory under tenders/ that wasn't (re)written above is either a
    # tender no longer in the feed, or one just excluded above as retired.
    # Only remove it if its own previously-generated page confirms a deadline
    # more than CLEANUP_AFTER_DAYS in the past — if we can't positively read
    # a past deadline from it (no "expires" field, unparseable, or the
    # deadline is still within the cutoff window) it's left alone untouched.
    removed = 0
    tenders_root = out / "tenders"
    if tenders_root.is_dir():
        for child in tenders_root.iterdir():
            if not child.is_dir() or child.name in seen_slugs:
                continue
            existing_html = child / "index.html"
            if not existing_html.exists():
                continue
            try:
                text = existing_html.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            m = re.search(r'"expires":\s*"([^"]+)"', text)
            if not m:
                continue
            try:
                old_dl = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                if old_dl.tzinfo is None:
                    old_dl = old_dl.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if old_dl < cleanup_cutoff:
                shutil.rmtree(child)
                removed += 1

    print(f"Generated {generated} tender pages → {out}/tenders/")
    print(f"Generated {hubs_generated} hub pages → {out}/tenders/sector/, {out}/tenders/region/")
    print(f"Sitemap   → {sitemap_path}  ({len(sitemap_entries)} URLs)")
    if skipped:
        print(f"Skipped   {skipped} tenders (no title)")
    if retired:
        print(f"Retired   {retired} tenders from this run (deadline more than {CLEANUP_AFTER_DAYS} days past)")
    if removed:
        print(f"Removed   {removed} stale tender page(s) from disk (confirmed deadline more than {CLEANUP_AFTER_DAYS} days past)")


if __name__ == "__main__":
    main()
