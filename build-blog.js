const fs   = require('fs');
const path = require('path');

const blogDir       = path.join(__dirname, '_blog');
const outputJson    = path.join(__dirname, 'blog-data.json');
const outputHtmlDir = path.join(__dirname, 'blog');
const sitemapPath   = path.join(__dirname, 'sitemap-blog.xml');
const baseUrl       = 'https://hawkeye-solutions.co.uk';

// ── Ensure /blog/ output directory exists ─────────────────────────────────
if (!fs.existsSync(outputHtmlDir)) {
  fs.mkdirSync(outputHtmlDir, { recursive: true });
}

if (!fs.existsSync(blogDir)) {
  console.log('No _blog directory found, creating empty outputs');
  fs.writeFileSync(outputJson, JSON.stringify([], null, 2));
  fs.writeFileSync(sitemapPath, buildSitemapXml([]));
  process.exit(0);
}

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
  const lines  = text.split('\n');
  let currentKey   = null;
  let currentValue = [];
  for (const line of lines) {
    const keyMatch = line.match(/^([\w-]+):\s*(.*)/);
    if (keyMatch) {
      if (currentKey) {
        result[currentKey] = currentValue.join(' ').trim().replace(/^['"]|['"]$/g, '');
      }
      currentKey   = keyMatch[1];
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
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d)) return dateStr;
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

function formatDateIso(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d)) return '';
  return d.toISOString().split('T')[0];
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

function escXml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function categoryLabel(c) {
  const map = {
    'bid-writing':  'Bid Writing',
    'procurement':  'Procurement Basics',
    'sector':       'Sector Guides',
    'mistakes':     'Common Mistakes',
  };
  return map[c] || (c ? c.charAt(0).toUpperCase() + c.slice(1) : 'General');
}

function categoryColour(c) {
  const map = {
    'bid-writing':  { bg: '#e8f4f7', text: '#0e4a57' },
    'procurement':  { bg: '#eef0fb', text: '#3a3faa' },
    'sector':       { bg: '#eaf7f1', text: '#1a7a50' },
    'mistakes':     { bg: '#fef6e8', text: '#b7670a' },
  };
  return map[c] || { bg: '#e8f4f7', text: '#0e4a57' };
}

function getInitials(name) {
  if (!name) return 'HS';
  return name.split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase();
}

// ── Simple Markdown → HTML converter ─────────────────────────────────────
// Handles headings, bold, italic, links, bullet lists, numbered lists,
// blockquotes, horizontal rules and paragraphs.
function markdownToHtml(md) {
  if (!md) return '';
  const lines   = md.split('\n');
  const output  = [];
  let inList     = false;
  let listType   = '';
  let inOl       = false;

  function closeList() {
    if (inList) {
      output.push(listType === 'ul' ? '</ul>' : '</ol>');
      inList   = false;
      listType = '';
    }
  }

  function inlineFormat(text) {
    // Bold + italic ***text***
    text = text.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
    // Bold **text**
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic *text*
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    // Inline code `text`
    text = text.replace(/`([^`]+)`/g, '<code style="background:#f0f0f0;padding:2px 6px;border-radius:4px;font-size:0.9em">$1</code>');
    // Links [text](url)
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" style="color:var(--teal-mid);font-weight:500">$1</a>');
    return text;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Heading 1
    if (/^# /.test(line)) {
      closeList();
      output.push(`<h2 style="font-size:26px;font-weight:800;color:var(--steel);margin:40px 0 14px">${inlineFormat(line.slice(2))}</h2>`);
      continue;
    }
    // Heading 2
    if (/^## /.test(line)) {
      closeList();
      output.push(`<h2 style="font-size:22px;font-weight:800;color:var(--steel);margin:36px 0 14px">${inlineFormat(line.slice(3))}</h2>`);
      continue;
    }
    // Heading 3
    if (/^### /.test(line)) {
      closeList();
      output.push(`<h3 style="font-size:18px;font-weight:700;color:var(--steel);margin:28px 0 10px">${inlineFormat(line.slice(4))}</h3>`);
      continue;
    }
    // Horizontal rule
    if (/^---$/.test(line.trim()) || /^\*\*\*$/.test(line.trim())) {
      closeList();
      output.push('<hr style="border:none;border-top:1px solid var(--border);margin:32px 0">');
      continue;
    }
    // Blockquote
    if (/^> /.test(line)) {
      closeList();
      output.push(`<blockquote style="border-left:4px solid var(--teal-mid);background:var(--teal-light);padding:16px 20px;border-radius:0 8px 8px 0;margin:24px 0;font-style:italic;color:var(--teal-dark)">${inlineFormat(line.slice(2))}</blockquote>`);
      continue;
    }
    // Unordered list item
    if (/^[-*] /.test(line)) {
      if (!inList || listType !== 'ul') {
        closeList();
        output.push('<ul style="list-style:none;padding:0;margin:0 0 20px">');
        inList   = true;
        listType = 'ul';
      }
      output.push(`<li style="padding:5px 0 5px 26px;position:relative;font-size:15px;color:var(--text)"><span style="position:absolute;left:0;top:13px;width:8px;height:8px;border-radius:50%;background:var(--teal-mid);display:inline-block"></span>${inlineFormat(line.slice(2))}</li>`);
      continue;
    }
    // Ordered list item
    if (/^\d+\. /.test(line)) {
      if (!inList || listType !== 'ol') {
        closeList();
        output.push('<ol style="list-style:none;padding:0;margin:0 0 20px;counter-reset:ol-counter">');
        inList   = true;
        listType = 'ol';
      }
      const text = line.replace(/^\d+\. /, '');
      output.push(`<li style="padding:5px 0 5px 30px;position:relative;font-size:15px;color:var(--text);counter-increment:ol-counter"><span style="position:absolute;left:0;top:5px;font-weight:700;color:var(--teal-mid);font-size:14px;counter-increment:none">${line.match(/^(\d+)\./)[1]}.</span>${inlineFormat(text)}</li>`);
      continue;
    }
    // Empty line
    if (line.trim() === '') {
      closeList();
      continue;
    }
    // Regular paragraph
    closeList();
    output.push(`<p style="margin-bottom:20px;font-size:15px;line-height:1.85;color:var(--text)">${inlineFormat(line)}</p>`);
  }

  closeList();
  return output.join('\n');
}

// ── Sitemap XML builder ───────────────────────────────────────────────────
function buildSitemapXml(posts) {
  const today = new Date().toISOString().split('T')[0];
  const urls  = posts.map(p => `  <url>
    <loc>${baseUrl}/blog/${escXml(p.slug)}.html</loc>
    <lastmod>${p.date ? formatDateIso(p.date) : today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>`).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>`;
}

// ── Generate static HTML for one blog post ────────────────────────────────
function generateHtml(post, allPosts) {
  const slug         = post.slug;
  const canonicalUrl = `${baseUrl}/blog/${slug}.html`;
  const pageTitle    = post.metaTitle    || post.title || 'Blog Post';
  const metaDesc     = post.metaDescription || post.excerpt || `${post.title} — expert bid writing insight from Hawkeye Solutions.`;
  const titleEsc     = escHtml(post.title);
  const authorEsc    = escHtml(post.author || 'Hawkeye Solutions');
  const catLabel     = categoryLabel(post.category);
  const catColour    = categoryColour(post.category);
  const initials     = getInitials(post.author);
  const bodyHtml     = markdownToHtml(post.body || '');
  const readTime     = post.readingTime || post.reading_time || '';

  // Related posts — same category first, then others, max 3
  const related = allPosts
    .filter(p => p.slug !== slug)
    .sort((a, b) => (b.category === post.category ? 1 : 0) - (a.category === post.category ? 1 : 0))
    .slice(0, 3);

  const relatedHtml = related.length ? related.map(r => `
    <a href="/blog/${escHtml(r.slug)}.html" style="display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border);text-decoration:none;color:inherit">
      <div style="width:52px;height:52px;border-radius:8px;background:var(--teal-light);flex-shrink:0;display:flex;align-items:center;justify-content:center">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--teal-mid)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
      </div>
      <div>
        <div style="font-size:13px;font-weight:600;color:var(--steel);line-height:1.4;margin-bottom:4px">${escHtml(r.title)}</div>
        <div style="font-size:12px;color:var(--text-muted)">${formatDateLong(r.date)}</div>
      </div>
    </a>`).join('') : '<p style="font-size:13px;color:var(--text-muted)">More articles coming soon.</p>';

  const schema = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": post.title,
    "description": metaDesc.substring(0, 200),
    "author": {
      "@type": "Person",
      "name": post.author || "Hawkeye Solutions"
    },
    "publisher": {
      "@type": "Organization",
      "name": "Hawkeye Solutions",
      "url": baseUrl
    },
    "datePublished": post.date || '',
    "url": canonicalUrl
  });

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="${escHtml(metaDesc.substring(0, 158))}">
<meta name="robots" content="index, follow">
<title>${escHtml(pageTitle)} | Hawkeye Solutions</title>
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
.nav-links a:hover,.nav-links a.active{color:var(--white)}
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
.breadcrumb{background:var(--off-white);border-bottom:1px solid var(--border);padding:12px 5%;font-size:13px;color:var(--text-muted)}
.breadcrumb a{color:var(--teal-mid);font-weight:500}
.breadcrumb a:hover{text-decoration:underline}
.post-container{max-width:1160px;margin:0 auto;padding:48px 5%;display:grid;grid-template-columns:1fr 300px;gap:52px;align-items:start}
footer{background:var(--steel);color:rgba(255,255,255,0.6);padding:36px 5%;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;font-size:13px}
footer .brand{color:rgba(255,255,255,0.9);font-weight:700}
@media(max-width:900px){.post-container{grid-template-columns:1fr;gap:36px}}
@media(max-width:600px){.post-container{padding:28px 5%}.nav-links{display:none}.hamburger{display:flex}}
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
    <a href="/blog.html" class="active">Blog</a>
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
  <a href="/blog.html">&#8592; Blog</a> &rsaquo; ${titleEsc}
</div>

<div class="post-container">
  <!-- MAIN CONTENT -->
  <div>
    <span style="display:inline-block;font-size:11px;font-weight:700;padding:4px 12px;border-radius:12px;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:16px;background:${catColour.bg};color:${catColour.text}">${escHtml(catLabel)}</span>
    <h1 style="font-size:34px;font-weight:800;color:var(--steel);line-height:1.25;margin-bottom:18px">${titleEsc}</h1>
    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:13px;color:var(--text-muted);margin-bottom:28px">
      <span style="font-weight:600;color:var(--steel)">${authorEsc}</span>
      <span style="opacity:0.4">&middot;</span>
      <span>${formatDateLong(post.date)}</span>
      ${readTime ? `<span style="opacity:0.4">&middot;</span><span>${escHtml(readTime)}</span>` : ''}
    </div>
    ${post.excerpt ? `<div style="background:var(--teal-light);border-radius:12px;padding:28px 32px;margin-bottom:36px;border-left:4px solid var(--teal-mid)"><p style="font-size:17px;color:var(--teal-dark);line-height:1.7;font-style:italic">${escHtml(post.excerpt)}</p></div>` : ''}
    <div>${bodyHtml}</div>
    <div style="background:linear-gradient(135deg,var(--steel),var(--teal-dark));border-radius:12px;padding:36px;margin-top:40px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:20px">
      <div>
        <h3 style="font-size:20px;font-weight:800;color:var(--white);margin-bottom:8px">Need help with your next bid?</h3>
        <p style="font-size:14px;color:rgba(255,255,255,0.72);max-width:380px">Our specialist bid writers can assess your fit for any opportunity and build a winning submission. Free initial consultation.</p>
      </div>
      <a href="/index.html#contact" style="background:var(--teal-mid);color:var(--white);padding:12px 26px;border-radius:7px;font-weight:700;font-size:14px;white-space:nowrap;display:inline-block">Get in Touch</a>
    </div>
  </div>

  <!-- SIDEBAR -->
  <aside style="display:flex;flex-direction:column;gap:24px">
    <div style="background:var(--off-white);border:1px solid var(--border);border-radius:12px;padding:24px;text-align:center">
      <p style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--teal-dark);margin-bottom:16px">About the Author</p>
      <div style="width:64px;height:64px;border-radius:50%;background:var(--teal-dark);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:800;color:var(--white);margin:0 auto 12px">${escHtml(initials)}</div>
      <div style="font-size:16px;font-weight:700;color:var(--steel);margin-bottom:4px">${authorEsc}</div>
      <div style="font-size:12px;color:var(--teal-mid);font-weight:600;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.5px">Bid Writing Expert</div>
      <div style="font-size:13px;color:var(--text-muted);line-height:1.6">Specialist in public sector procurement and bid writing, helping UK businesses win contracts across recruitment, IT and professional services.</div>
    </div>

    <div style="background:var(--off-white);border:1px solid var(--border);border-radius:12px;padding:24px">
      <p style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--teal-dark);margin-bottom:16px">Related Articles</p>
      ${relatedHtml}
    </div>

    <div style="background:var(--off-white);border:1px solid var(--border);border-radius:12px;padding:24px;text-align:center">
      <p style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--teal-dark);margin-bottom:12px">Get in Touch</p>
      <p style="font-size:13px;color:var(--text-muted);line-height:1.6;margin-bottom:16px">Have a tender you want to win? Our bid specialists are ready to help you put together a standout submission.</p>
      <a href="/index.html#contact" style="display:block;background:var(--teal-dark);color:var(--white);padding:11px 18px;border-radius:7px;font-size:13px;font-weight:700;text-align:center">Free Consultation</a>
    </div>
  </aside>
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
if(window.netlifyIdentity){window.netlifyIdentity.on('init',function(user){if(!user){window.netlifyIdentity.on('login',function(){document.location.href='/admin/';})}});}
</script>
</body>
</html>`;
}

// ── Process all blog files ────────────────────────────────────────────────
const files = fs.readdirSync(blogDir).filter(f => f.endsWith('.md'));
console.log(`Found ${files.length} blog file(s) in _blog`);

const posts = [];

for (const file of files) {
  const raw = fs.readFileSync(path.join(blogDir, file), 'utf8').replace(/\r\n/g, '\n');

  const fmMatch = raw.match(/^---\n([\s\S]*?)\n---/);
  if (!fmMatch) {
    console.warn(`  Skipping ${file} — no frontmatter found`);
    continue;
  }

  const data = parseFrontmatter(fmMatch[1]);

  if ((data.status || '').toLowerCase() !== 'published') {
    console.log(`  Skipping ${file} (status: ${data.status || 'not set'})`);
    continue;
  }

  const bodyRaw   = raw.slice(fmMatch[0].length);
  const bodyClean = bodyRaw.replace(/^\n+/, '').trimEnd();

  const post = {
    slug:            data.slug            || file.replace(/\.md$/, ''),
    title:           data.title           || '',
    date:            normaliseDate(data.date || ''),
    author:          data.author          || '',
    category:        data.category        || '',
    excerpt:         data.excerpt         || '',
    metaTitle:       data.metaTitle       || data['meta-title'] || '',
    metaDescription: data.metaDescription || data['meta-description'] || '',
    readingTime:     data.readingTime     || data['reading-time'] || data.reading_time || '',
    status:          data.status          || '',
    body:            bodyClean,
  };

  posts.push(post);
}

// Sort newest first
posts.sort((a, b) => {
  const da = a.date ? new Date(a.date) : new Date(0);
  const db = b.date ? new Date(b.date) : new Date(0);
  return db - da;
});

// Generate static HTML for each post
for (const post of posts) {
  const htmlPath = path.join(outputHtmlDir, `${post.slug}.html`);
  fs.writeFileSync(htmlPath, generateHtml(post, posts), 'utf8');
  console.log(`  Generated: blog/${post.slug}.html`);
}

// Write blog-data.json
fs.writeFileSync(outputJson, JSON.stringify(posts, null, 2));

// Write sitemap-blog.xml
fs.writeFileSync(sitemapPath, buildSitemapXml(posts));

console.log(`Written ${posts.length} published post(s) to blog-data.json`);
console.log(`sitemap-blog.xml updated (${posts.length} posts)`);
