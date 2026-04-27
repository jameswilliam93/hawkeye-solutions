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

const tenders = [];

for (const file of files) {
  const content = fs.readFileSync(path.join(tendersDir, file), 'utf8').replace(/\r\n/g, '\n');
  const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
  if (!frontmatterMatch) continue;

  const data = parseFrontmatter(frontmatterMatch[1]);

  tenders.push({
    slug: file.replace('.md', ''),
    title: data.title || '',
    reference: data.reference || '',
    status: data.status || 'live',
    date: normaliseDate(data.date || ''),
    deadline: normaliseDate(data.deadline || ''),
    value: data.value || '',
    sector: data.sector || '',
    location: data.location || '',
    contracting_authority: data.contracting_authority || '',
    description: data.description || '',
  });
}

tenders.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));

fs.writeFileSync(outputJson, JSON.stringify(tenders, null, 2));
console.log(`Written ${tenders.length} tenders to tenders-data.json`);
