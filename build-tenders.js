const fs = require('fs');
const path = require('path');

const tendersDir = path.join(__dirname, '_tenders');
const outputJson = path.join(__dirname, 'tenders-data.json');

if (!fs.existsSync(tendersDir)) {
  console.log('No _tenders directory found, creating empty tenders-data.json');
  fs.writeFileSync(outputJson, JSON.stringify([], null, 2));
  process.exit(0);
}

const files = fs.readdirSync(tendersDir).filter(f => f.endsWith('.md'));
console.log(`Found ${files.length} tender files`);

function normaliseDate(val) {
  if (!val) return '';
  val = val.trim().replace(/^['"]|['"]$/g, '');
  // Strip time component if present
  val = val.split('T')[0];
  // Handle DD/MM/YYYY format
  const dmyMatch = val.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (dmyMatch) {
    return `${dmyMatch[3]}-${dmyMatch[2]}-${dmyMatch[1]}`;
  }
  return val;
}

const tenders = [];

for (const file of files) {
  const content = fs.readFileSync(path.join(tendersDir, file), 'utf8').replace(/\r\n/g, '\n');
  const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
  if (!frontmatterMatch) continue;

  const fm = frontmatterMatch[1];

  const get = key => {
    const match = fm.match(new RegExp(`^${key}:\\s*([\\s\\S]*?)(?=\\n[\\w-]+:|$)`, 'm'));
    if (!match) return '';
    // Handle YAML block scalars - join continuation lines
    return match[1]
      .split('\n')
      .map(line => line.replace(/^\s+/, ''))
      .join(' ')
      .trim()
      .replace(/^['"]|['"]$/g, '');
  };

  tenders.push({
    slug: file.replace('.md', ''),
    title: get('title'),
    reference: get('reference'),
    status: get('status'),
    date: normaliseDate(get('date')),
    deadline: normaliseDate(get('deadline')),
    value: get('value'),
    sector: get('sector'),
    location: get('location'),
    contracting_authority: get('contracting_authority'),
    description: get('description'),
  });
}

tenders.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));

fs.writeFileSync(outputJson, JSON.stringify(tenders, null, 2));
console.log(`Written ${tenders.length} tenders to tenders-data.json`);
