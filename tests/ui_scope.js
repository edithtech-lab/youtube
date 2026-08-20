// let/const 로 선언한 변수를 window.X 로 읽으면 항상 undefined 다 (2026-08-20 실측 사고).
// 📇 등장 대상 줄이 한 번도 안 뜬 원인이었고, 등록부 사물 저장 경로도 이 함정으로 어긋났다.
const fs = require('fs');
const s = fs.readFileSync(require('path').join(__dirname, '..', 'ui', 'index.html'), 'utf8');
const declared = new Set();
for (const m of s.matchAll(/(?:let|const)\s+(_[A-Za-z][A-Za-z0-9_]*)/g)) declared.add(m[1]);
const used = new Set();
for (const m of s.matchAll(/window\.(_[A-Za-z][A-Za-z0-9_]*)/g)) used.add(m[1]);
const assigned = new Set();
for (const m of s.matchAll(/window\.(_[A-Za-z][A-Za-z0-9_]*)\s*=/g)) assigned.add(m[1]);
const bad = [...used].filter(v => declared.has(v) && !assigned.has(v)).sort();
if (bad.length) {
  console.log('❌ let/const 인데 window 로 읽는 변수 (항상 undefined):', bad.join(', '));
  process.exit(1);
}
console.log('✅ window 참조 정합성 통과');
