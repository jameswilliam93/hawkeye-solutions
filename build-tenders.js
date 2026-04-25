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

const tenders = [];

for (const file of files) {
  const content = fs.readFileSync(path.join(tendersDir, file), 'utf8').replace(/\r\n/g, '\n');
  const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
  if (!frontmatterMatch) continue;

  const fm = frontmatterMatch[1];
  const get = key => {
    const match = fm.match(new RegExp(`^${key}:\\s*(.+)$`, 'm'));
    return match ? match[1].trim().replace(/^['"]|['"]$/g, '') : '';
  };

  tenders.push({
    slug: file.replace('.md', ''),
    title: get('title'),
    reference: get('reference'),
    status: get('status'),
    date: get('date'),
    deadline: get('deadline'),
    value: get('value'),
    sector: get('sector'),
    location: get('location'),
    contracting_authority: get('contracting_authority'),
    description: get('description')
  });
}

tenders.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));

fs.writeFileSync(outputJson, JSON.stringify(tenders, null, 2));
console.log(`Written ${tenders.length} tenders to tenders-data.json`);
