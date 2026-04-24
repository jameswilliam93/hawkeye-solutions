// build-tenders.js
// Run by Netlify at build time to generate tenders-data.json and _tenders/index.json
// This makes tenders readable by the public tender board

const fs = require('fs');
const path = require('path');

const tendersDir = path.join(__dirname, '_tenders');
const outputJson = path.join(__dirname, 'tenders-data.json');
const outputIndex = path.join(__dirname, '_tenders', 'index.json');

function parseFrontmatter(content, filename) {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return null;
  const lines = match[1].split('\n');
  const data = {};
  let currentKey = null;
  for (const line of lines) {
    if (line.match(/^[a-z_]+:/i)) {
      const colonIdx = line.indexOf(':');
      currentKey = line.substring(0, colonIdx).trim();
      const val = line.substring(colonIdx + 1).trim();
      data[currentKey] = val.replace(/^["']|["']$/g, '');
    }
  }
  data._slug = filename.replace(/\.md$/, '');
  data._filename = filename;
  // Get body
  const body = content.replace(/^---\n[\s\S]*?\n---\n?/, '').trim();
  if (body && !data.description) data.description = body;
  return data;
}

if (!fs.existsSync(tendersDir)) {
  fs.mkdirSync(tendersDir, { recursive: true });
  console.log('Created _tenders directory');
}

const files = fs.readdirSync(tendersDir).filter(f => f.endsWith('.md'));
console.log(`Found ${files.length} tender files`);

const tenders = [];
for (const file of files) {
  try {
    const content = fs.readFileSync(path.join(tendersDir, file), 'utf8');
    const data = parseFrontmatter(content, file);
    if (data) {
      tenders.push(data);
      console.log(`Parsed: ${file}`);
    }
  } catch (e) {
    console.error(`Error parsing ${file}:`, e.message);
  }
}

// Sort newest first
tenders.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));

// Write tenders-data.json (used as fallback by the public board)
fs.writeFileSync(outputJson, JSON.stringify(tenders, null, 2));
console.log(`Written tenders-data.json with ${tenders.length} tenders`);

// Write index.json (list of filenames)
fs.writeFileSync(outputIndex, JSON.stringify(files));
console.log(`Written _tenders/index.json`);
