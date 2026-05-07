const fs = require('fs');
const path = require('path');

const tendersDir = path.join(__dirname, '_tenders');
const outputJson = path.join(__dirname, 'tenders-data.json');
const outputHtmlDir = path.join(__dirname, 'tenders');

// ── Ensure /tenders/ output directory exists ──────────────────────────────
if (!fs.existsSync(outputHtmlDir)) {
  fs.mkdirSync(outputHtmlDir, { recursive: true });
}

if (!fs.existsSync(tendersDir)) {
  console.log('No _tenders directory found, creating empty tenders-data.json');
  fs.writeFileSync(outputJson, JSON.stringify([], null, 2));
  process.exit(0);
}

const files = fs.readdirSync(tendersDir).filter(f => f.endsWith('.md'));
console.log(`Found ${files.length} tender files`);

// ── Helpers ───────────────────────────────────────────────────────────────
function normaliseDate(val) {
  if (!val) return '';
  val = val.trim().replace(/^['"]|['"]$/g, '').split('T')[0];
  const dmyMatch = val.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (dmyMatch) return `${dmyMatch[3]}-${dmyMatch[2]}-${dmyMatch[1]}`;
  return val;
}

function parseFrontmatter(text) {
  const result = {};
  const lines = text.split('\n');
  let currentKey = null;
  let currentValue = [];
  for (const line of lines) {
    const keyMatch = line.match(/^([\w-]+):\s*(.*)/);
    if (keyMatch) {
      if (currentKey) {
        result[currentKey] = currentValue.join(' ').trim().replace(/^['"]|['"]$/g, '');
      }
      currentKey = keyMatch[1];
      currentValue = [keyMatch[2]];
    } else if (currentKey && line.match(/^\s+\S/)) {
      currentValue.push(line.trim());
    }
  }
  if (currentKey) {
    result[currentKey] = currentValue.join(' ').trim().replace(/^['"]|['"]$/g, '');
  }
  return result;
}

function formatDateLong(dateStr) {
  if (!dateStr) return 'TBC';
  const d = new Date(dateStr);
  if (isNaN(d)) return dateStr;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

function daysUntil(dateStr) {
  if (!dateStr) return 999;
  const d = new Date(dateStr);
  const n = new Date();
  n.setHours(0, 0, 0, 0);
  return Math.ceil((d - n) / 86400000);
}

function sectorLabel(s) {
  return s === 'recruitment' ? 'Recruitment and Staffing'
       : s === 'it'          ? 'IT and Technology'
       : 'Other';
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function deadlineColour(days) {
  if (days <= 0)  return '#c0392b';
  if (days <= 14) return '#b7670a';
  return '#1a7a50';
}

function deadlineBg(days) {
  if (days <= 0)  return '#fdf0ee';
  if (days <= 14) return '#fef6e8';
  return '#eaf7f1';
}

// ── Build meta description (under 160 chars) ─────────────────────────────
function buildMetaDesc(t) {
  const base = `${t.title} — ${t.contracting_authority || 'UK public sector'} tender. `;
  const detail = t.value ? `Est. value ${t.value}. ` : '';
  const deadline = t.deadline ? `Deadline ${formatDateLong(t.deadline)}. ` : '';
  const cta = 'Hawkeye Solutions can help you win. Free consultation available.';
  let desc = base + detail + deadline + cta;
  if (desc.length > 158) desc = base + detail + cta;
  if (desc.length > 158) desc = base + cta;
  return desc.substring(0, 158);
}

// ── Generate static HTML for one tender ──────────────────────────────────
function generateHtml(t) {
  const days      = daysUntil(t.deadline);
  const daysLabel = days <= 0  ? 'Deadline passed'
                  : days === 1 ? '1 day remaining'
                  : `${days} days remaining`;
  const canonicalUrl = `https://hawkeye-solutions.co.uk/tenders/${t.slug}.html`;
  const metaDesc     = buildMetaDesc(t);
  const titleEsc     = escHtml(t.title);
  const authorityEsc = escHtml(t.contracting_authority);
  const descEsc      = escHtml(t.description).replace(/\n/g, '<br>');
  const dColour      = deadlineColour(days);
  const dBg          = deadlineBg(days);

  // Schema.org JobPosting is the closest match Google understands for tenders
  const schema = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "GovernmentService",
    "name": t.title,
    "description": t.description ? t.description.substring(0, 300) : '',
    "provider": {
      "@type": "Organization",
      "name": t.contracting_authority || '',
      "url": "https://hawkeye-solutions.co.uk"
    },
    "areaServed": t.location || "United Kingdom",
    "url": canonicalUrl
  });

  function detailRow(label, value) {
    if (!value || value === 'null' || value === 'undefined' || value === '') return '';
    return `<div class="detail-row">
      <div class="detail-label">${label}</div>
      <div class="detail-value">${escHtml(value)}</div>
    </div>`;
  }

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="${escHtml(metaDesc)}">
<meta name="robots" content="index, follow">
<title>${titleEsc} | ${escHtml(t.contracting_authority || 'UK Tender')} | Hawkeye Solutions</title>
<link rel="canonical" href="${canonicalUrl}">
<link rel="icon" type="image/png" href="/favicon-96x96.png" sizes="96x96" />
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<link rel="shortcut icon" href="/favicon.ico" />
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png" />
<link rel="manifest" href="/site.webmanifest" />
<script async src="https://www.googletagmanager.com/gtag/js?id=G-5RKL8KRV0S"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-5RKL8KRV0S');</script>
<script type="application/ld+json">${schema}</script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--teal:#1a6b7c;--teal-dark:#0e4a57;--teal-light:#e8f4f7;--teal-mid:#2a8fa3;--steel:#1c3d4f;--white:#fff;--off-white:#f7fbfc;--text:#1a2e35;--text-muted:#4a6572;--border:#d0e8ee}
body{font-family:'Segoe UI',Arial,sans-serif;color:var(--text);background:var(--white)}
a{text-decoration:none;color:inherit}
nav{background:var(--steel);padding:0 5%;display:flex;align-items:center;justify-content:space-between;height:68px;position:sticky;top:0;z-index:100}
.nav-logo{display:flex;align-items:center;gap:12px}
.nav-brand{color:var(--white);font-size:18px;font-weight:700}
.nav-links{display:flex;gap:28px}
.nav-links a{color:rgba(255,255,255,0.85);font-size:14px;font-weight:500;transition:color 0.2s}
.nav-links a:hover{color:var(--white)}
.nav-cta{background:var(--teal-mid)!important;color:var(--white)!important;padding:8px 18px;border-radius:6px;font-weight:600!important}
.hamburger{display:none;flex-direction:column;justify-content:space-between;width:24px;height:18px;background:none;border:none;cursor:pointer;padding:0;flex-shrink:0}
.hamburger span{display:block;width:100%;height:2px;background:var(--white);border-radius:2px;transition:transform 0.25s,opacity 0.25s}
.hamburger.open span:nth-child(1){transform:translateY(8px) rotate(45deg)}
.hamburger.open span:nth-child(2){opacity:0}
.hamburger.open span:nth-child(3){transform:translateY(-8px) rotate(-45deg)}
.mobile-menu{display:none;position:absolute;top:68px;left:0;right:0;background:var(--steel);z-index:99;flex-direction:column;border-top:1px solid rgba(255,255,255,0.1);box-shadow:0 8px 24px rgba(0,0,0,0.2)}
.mobile-menu.open{display:flex}
.mobile-menu a{color:rgba(255,255,255,0.85);font-size:15px;font-weight:500;padding:14px 5%;border-bottom:1px solid rgba(255,255,255,0.07)}
.mobile-menu a:last-child{border-bottom:none}
.mobile-menu a:hover{background:rgba(255,255,255,0.07);color:var(--white)}
.mobile-menu .mob-cta{background:var(--teal-mid);color:var(--white);margin:12px 5%;border-radius:6px;text-align:center;border-bottom:none!important;padding:12px 5%}
.breadcrumb{padding:14px 5%;font-size:13px;color:var(--text-muted);background:var(--off-white);border-bottom:1px solid var(--border)}
.breadcrumb a{color:var(--teal-mid);font-weight:500}
.breadcrumb a:hover{text-decoration:underline}
.detail-header{background:linear-gradient(135deg,var(--steel),var(--teal-dark));padding:52px 5% 44px}
.status-badge{display:inline-block;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:14px;background:rgba(125,212,100,0.2);color:#7dd464}
.sector-badge{display:inline-block;font-size:11px;font-weight:700;padding:4px 12px;border-radius:12px;margin-left:8px;text-transform:uppercase;background:rgba(232,244,247,0.2);color:#a0d8e8}
.detail-header h1{font-size:36px;font-weight:800;color:var(--white);line-height:1.2;margin-bottom:8px;max-width:760px}
.detail-header .authority{font-size:17px;color:rgba(255,255,255,0.75);margin-top:6px}
.content-grid{display:grid;grid-template-columns:1fr 340px;gap:32px;padding:44px 5%;align-items:start;max-width:1200px}
.section-block{background:var(--white);border:1px solid var(--border);border-radius:12px;padding:28px;margin-bottom:22px}
.section-block h2{font-size:18px;font-weight:700;color:var(--steel);margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--border)}
.section-block p{font-size:15px;color:var(--text-muted);line-height:1.85}
.detail-row{display:flex;gap:16px;padding:11px 0;border-bottom:1px solid var(--border)}
.detail-row:last-child{border-bottom:none}
.detail-label{font-size:13px;font-weight:600;color:var(--steel);width:170px;flex-shrink:0}
.detail-value{font-size:13px;color:var(--text-muted);flex:1;line-height:1.5}
.deadline-card{border-radius:12px;padding:20px;margin-bottom:18px;display:flex;align-items:center;gap:16px;border:1px solid ${dBg === '#eaf7f1' ? '#a3dcc0' : dBg === '#fef6e8' ? '#f0c070' : '#f0a090'};background:${dBg}}
.deadline-days{font-size:28px;font-weight:800;color:${dColour};line-height:1}
.deadline-label{font-size:12px;color:var(--text-muted);margin-top:2px}
.deadline-date-label{font-size:12px;color:var(--text-muted);margin-bottom:3px}
.deadline-date-val{font-size:14px;font-weight:700;color:var(--steel)}
.btn-primary{display:block;width:100%;background:var(--teal-dark);color:var(--white);border:none;padding:14px;border-radius:8px;font-size:15px;font-weight:700;cursor:pointer;text-align:center;margin-bottom:12px;transition:background 0.2s}
.btn-primary:hover{background:var(--teal)}
.btn-secondary{display:block;width:100%;background:var(--white);color:var(--teal-dark);border:2px solid var(--border);padding:12px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;text-align:center;margin-bottom:12px;transition:all 0.2s}
.btn-secondary:hover{border-color:var(--teal-mid)}
.ref-badge{display:inline-block;background:var(--teal-light);color:var(--teal-dark);font-size:13px;font-weight:700;padding:6px 14px;border-radius:7px;margin-bottom:20px;font-family:monospace;letter-spacing:0.5px}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:500;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal{background:var(--white);border-radius:16px;width:90%;max-width:540px;padding:36px;position:relative;max-height:90vh;overflow-y:auto}
.modal h2{font-size:22px;font-weight:800;color:var(--steel);margin-bottom:6px}
.modal .sub{font-size:14px;color:var(--text-muted);margin-bottom:24px}
.form-group{margin-bottom:14px}
.form-group label{display:block;font-size:13px;font-weight:600;color:var(--steel);margin-bottom:5px}
.form-group input,.form-group textarea{width:100%;border:1px solid var(--border);border-radius:7px;padding:10px 13px;font-size:14px;color:var(--text);font-family:inherit;transition:border-color 0.2s}
.form-group input:focus,.form-group textarea:focus{outline:none;border-color:var(--teal-mid)}
.form-group textarea{min-height:90px;resize:vertical}
.form-submit{background:var(--teal-dark);color:var(--white);border:none;padding:13px;width:100%;border-radius:7px;font-size:15px;font-weight:700;cursor:pointer;margin-top:6px;transition:background 0.2s}
.form-submit:hover{background:var(--teal)}
.close-modal{position:absolute;top:16px;right:20px;background:none;border:none;font-size:22px;cursor:pointer;color:var(--text-muted)}
.success-msg{display:none;background:#e8f7f0;border:1px solid #a3dcc0;border-radius:8px;padding:16px;font-size:15px;color:#1a6b4a;font-weight:500;text-align:center;margin-top:12px}
.ohnohoney{opacity:0;position:absolute;top:0;left:0;height:0;width:0;z-index:-1}
footer{background:var(--steel);color:rgba(255,255,255,0.6);padding:36px 5%;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;font-size:13px}
footer .brand{color:rgba(255,255,255,0.9);font-weight:700}
@media(max-width:768px){
  .content-grid{grid-template-columns:1fr;padding:28px 5%}
  .nav-links{display:none}
  .hamburger{display:flex}
  .detail-header h1{font-size:26px}
}
</style>
</head>
<body>

<div style="position:relative">
<nav>
  <a href="/index.html" class="nav-logo">
    <img src="/logo.png" alt="Hawkeye Solutions" height="44" style="display:block">
    <span class="nav-brand">Hawkeye Solutions</span>
  </a>
  <div class="nav-links">
    <a href="/index.html">Home</a>
    <a href="/services.html">Services</a>
    <a href="/sectors.html">Sectors</a>
    <a href="/tenders.html">Tenders</a>
    <a href="/blog.html">Blog</a>
    <a href="/index.html#about">About Us</a>
    <a href="/index.html#contact" class="nav-cta">Free Consultation</a>
  </div>
  <button class="hamburger" id="hamburger-btn" aria-label="Open menu" aria-expanded="false" onclick="toggleMenu()">
    <span></span><span></span><span></span>
  </button>
</nav>
<div class="mobile-menu" id="mobile-menu">
  <a href="/index.html">Home</a>
  <a href="/services.html">Services</a>
  <a href="/sectors.html">Sectors</a>
  <a href="/tenders.html">Tenders</a>
  <a href="/blog.html">Blog</a>
  <a href="/index.html#about">About Us</a>
  <a href="/index.html#contact" class="mob-cta">Free Consultation</a>
</div>
</div>

<div class="breadcrumb">
  <a href="/tenders.html">&#8592; All Tenders</a> &rsaquo; ${titleEsc}
</div>

<div class="detail-header">
  <div style="margin-bottom:10px">
    <span class="status-badge">${escHtml((t.status || 'live').charAt(0).toUpperCase() + (t.status || 'live').slice(1))}</span>
    <span class="sector-badge">${escHtml(sectorLabel(t.sector))}</span>
  </div>
  <h1>${titleEsc}</h1>
  <div class="authority">${authorityEsc}${t.location ? ' &nbsp;&middot;&nbsp; ' + escHtml(t.location) : ''}</div>
  ${t.reference ? `<div style="margin-top:14px"><span class="ref-badge">Ref: ${escHtml(t.reference)}</span></div>` : ''}
</div>

<div class="content-grid">
  <div>
    <div class="section-block">
      <h2>About This Tender</h2>
      <p>${descEsc}</p>
    </div>

    <div class="section-block">
      <h2>Tender Details</h2>
      ${detailRow('Reference Number', t.reference)}
      ${detailRow('Sector', sectorLabel(t.sector))}
      ${detailRow('Location', t.location)}
      ${detailRow('Estimated Value', t.value)}
      ${detailRow('Contracting Authority', t.contracting_authority)}
      ${detailRow('Published', formatDateLong(t.date))}
      ${detailRow('Deadline', t.deadline ? formatDateLong(t.deadline) + ' (' + daysLabel + ')' : '')}
    </div>

    <div class="section-block" style="background:var(--teal-light);border-color:var(--teal-mid)">
      <h2 style="border-color:rgba(26,107,124,0.2)">Need Help Winning This Bid?</h2>
      <p style="margin-bottom:18px">Hawkeye Solutions specialises in bid writing for ${escHtml(sectorLabel(t.sector))} tenders. We can assess your fit for this opportunity and build a winning submission - completely free initial consultation.</p>
      <a href="/index.html#contact" class="btn-primary" style="max-width:280px">Book Free Consultation</a>
    </div>
  </div>

  <div>
    <div class="section-block">
      <div class="deadline-card">
        <div>
          <div class="deadline-days">${days > 0 ? days : '0'}</div>
          <div class="deadline-label">${days > 0 ? 'days remaining' : 'deadline passed'}</div>
        </div>
        <div>
          <div class="deadline-date-label">Submission deadline</div>
          <div class="deadline-date-val">${formatDateLong(t.deadline)}</div>
        </div>
      </div>
      ${t.value ? `<div style="font-size:13px;color:var(--text-muted);margin-bottom:18px">Estimated value: <strong style="color:var(--steel);font-size:15px">${escHtml(t.value)}</strong></div>` : ''}
      <button class="btn-primary" onclick="openModal()">Enquire About This Tender</button>
      <a href="/tenders.html" class="btn-secondary">Back to All Tenders</a>
    </div>

    <div class="section-block">
      <h2 style="font-size:15px">About Hawkeye Solutions</h2>
      <p style="font-size:13px;color:var(--text-muted);line-height:1.75;margin-bottom:14px">We are specialist bid writers for UK recruitment and IT consultancy businesses. We have helped clients win over £500m in public sector contracts.</p>
      <a href="/bid-writing.html" class="btn-secondary">Learn About Our Bid Writing</a>
    </div>
  </div>
</div>

<!-- ENQUIRY MODAL -->
<div class="modal-overlay" id="enquiry-modal">
  <div class="modal">
    <button class="close-modal" onclick="closeModal()">&#x2715;</button>
    <h2>Enquire About This Tender</h2>
    <p class="sub">Tender: ${titleEsc}</p>
    <form name="tender-enquiry" method="POST" data-netlify="true" netlify-honeypot="bot-field" onsubmit="handleSubmit(event)">
      <input type="hidden" name="form-name" value="tender-enquiry">
      <input type="hidden" name="tender-title" value="${titleEsc}">
      <input type="hidden" name="tender-ref" value="${escHtml(t.reference)}">
      <p class="ohnohoney"><label>Do not fill: <input name="bot-field" tabindex="-1"></label></p>
      <div class="form-group"><label>Full name *</label><input type="text" name="name" placeholder="Your full name" required></div>
      <div class="form-group"><label>Company name *</label><input type="text" name="company" placeholder="Your organisation" required></div>
      <div class="form-group"><label>Phone number *</label><input type="tel" name="phone" placeholder="Your contact number" required></div>
      <div class="form-group"><label>Email address *</label><input type="email" name="email" placeholder="you@company.com" required></div>
      <div class="form-group"><label>Briefly describe your requirement</label><textarea name="requirement" placeholder="Tell us how we can help with this tender..."></textarea></div>
      <button type="submit" class="form-submit">Submit Enquiry</button>
    </form>
    <div class="success-msg" id="modal-success">Thank you - one of our team will be in touch as soon as possible.</div>
  </div>
</div>

<footer>
  <span class="brand">Hawkeye Solutions</span>
  <span>Precision Bids. Proven Results.</span>
  <span>&copy; 2025 Hawkeye Solutions. All rights reserved.</span>
</footer>

<script>
function toggleMenu(){
  var btn=document.getElementById('hamburger-btn'),menu=document.getElementById('mobile-menu'),open=menu.classList.contains('open');
  if(open){menu.classList.remove('open');btn.classList.remove('open');btn.setAttribute('aria-expanded','false');}
  else{menu.classList.add('open');btn.classList.add('open');btn.setAttribute('aria-expanded','true');}
}
function openModal(){document.getElementById('enquiry-modal').classList.add('open');}
function closeModal(){document.getElementById('enquiry-modal').classList.remove('open');}
function handleSubmit(e){
  e.preventDefault();
  var form=e.target;
  fetch('/',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(form)).toString()})
    .then(function(){form.style.display='none';document.getElementById('modal-success').style.display='block';})
    .catch(function(){form.style.display='none';document.getElementById('modal-success').style.display='block';});
}
if(window.netlifyIdentity){window.netlifyIdentity.on('init',function(user){if(!user){window.netlifyIdentity.on('login',function(){document.location.href='/admin/';})}});}
</script>
</body>
</html>`;
}

// ── Process all tender files ──────────────────────────────────────────────
const tenders = [];

for (const file of files) {
  const content = fs.readFileSync(path.join(tendersDir, file), 'utf8').replace(/\r\n/g, '\n');
  const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
  if (!frontmatterMatch) {
    console.warn(`Skipping ${file} — no frontmatter found`);
    continue;
  }

  const data = parseFrontmatter(frontmatterMatch[1]);
  const slug = file.replace('.md', '');

  const tender = {
    slug,
    title:                 data.title || '',
    reference:             data.reference || '',
    status:                data.status || 'live',
    date:                  normaliseDate(data.date || ''),
    deadline:              normaliseDate(data.deadline || ''),
    value:                 data.value || '',
    sector:                data.sector || '',
    location:              data.location || '',
    contracting_authority: data.contracting_authority || '',
    description:           data.description || '',
    contact_name:          data.contact_name || '',
    contact_telephone:     data.contact_telephone || '',
    contact_email:         data.contact_email || '',
    lots:                  data.lots || '',
  };

  tenders.push(tender);

  // ── Write static HTML page ─────────────────────────────────────────────
  const htmlPath = path.join(outputHtmlDir, `${slug}.html`);
  fs.writeFileSync(htmlPath, generateHtml(tender), 'utf8');
  console.log(`  Generated: tenders/${slug}.html`);
}

// ── Sort newest first and write JSON ─────────────────────────────────────
tenders.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));
fs.writeFileSync(outputJson, JSON.stringify(tenders, null, 2));

console.log(`\nDone: ${tenders.length} tenders processed`);
console.log(`  tenders-data.json updated`);
console.log(`  Static pages written to /tenders/`);
