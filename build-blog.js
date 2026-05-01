const fs   = require('fs');
const path = require('path');

const blogDir    = path.join(__dirname, '_blog');
const outputJson = path.join(__dirname, 'blog-data.json');

// ── 1. Missing folder → empty output, clean exit ────────────────────────────
if (!fs.existsSync(blogDir)) {
  console.log('No _blog directory found, creating empty blog-data.json');
  fs.writeFileSync(outputJson, JSON.stringify([], null, 2));
  process.exit(0);
}

// ── 2. Helpers ───────────────────────────────────────────────────────────────

/**
 * Normalise dates from both YYYY-MM-DD and DD/MM/YYYY to YYYY-MM-DD.
 */
function normaliseDate(val) {
  if (!val) return '';
  val = val.trim().replace(/^['"]|['"]$/g, '').split('T')[0];
  const dmyMatch = val.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (dmyMatch) return `${dmyMatch[3]}-${dmyMatch[2]}-${dmyMatch[1]}`;
  return val;
}

/**
 * Robust line-by-line YAML parser (same approach as build-tenders.js).
 * Handles multi-word / multi-line values and strips surrounding quotes.
 */
function parseFrontmatter(text) {
  const result = {};
  const lines = text.split('\n');
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

// ── 3. Process files ─────────────────────────────────────────────────────────

const files = fs.readdirSync(blogDir).filter(f => f.endsWith('.md'));
console.log(`Found ${files.length} blog file(s) in _blog`);

const posts = [];

for (const file of files) {
  const raw = fs
    .readFileSync(path.join(blogDir, file), 'utf8')
    .replace(/\r\n/g, '\n');           // normalise Windows line endings

  // Must begin with a frontmatter block
  const fmMatch = raw.match(/^---\n([\s\S]*?)\n---/);
  if (!fmMatch) {
    console.warn(`  ⚠  Skipping ${file} — no frontmatter found`);
    continue;
  }

  const data = parseFrontmatter(fmMatch[1]);

  // ── 4. Published-only filter ──────────────────────────────────────────────
  if ((data.status || '').toLowerCase() !== 'published') {
    console.log(`  –  Skipping ${file} (status: ${data.status || 'not set'})`);
    continue;
  }

  // Body content = everything after the closing ---
  const bodyRaw   = raw.slice(fmMatch[0].length);
  const bodyClean = bodyRaw.replace(/^\n+/, '').trimEnd();

  posts.push({
    slug:            data.slug            || file.replace(/\.md$/, ''),
    title:           data.title           || '',
    date:            normaliseDate(data.date || ''),
    author:          data.author          || '',
    category:        data.category        || '',
    excerpt:         data.excerpt         || '',
    metaTitle:       data.metaTitle       || '',
    metaDescription: data.metaDescription || '',
    readingTime:     data.readingTime     || '',
    status:          data.status          || '',
    body:            bodyClean,
  });
}

// ── 5. Sort by date descending (newest first) ─────────────────────────────────
posts.sort((a, b) => {
  const da = a.date ? new Date(a.date) : new Date(0);
  const db = b.date ? new Date(b.date) : new Date(0);
  return db - da;
});

// ── 6. Write output ───────────────────────────────────────────────────────────
fs.writeFileSync(outputJson, JSON.stringify(posts, null, 2));
console.log(`Written ${posts.length} published post(s) to blog-data.json`);
