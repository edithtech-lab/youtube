// UI 정합성 검사 — script 블록 문법 + 톤 셀렉트/주석 셀렉트가 백엔드 값과 맞는지.
// 실행: node tests/ui_check.js  (index.html 은 같은 저장소의 ui/index.html)
const fs = require('fs'), vm = require('vm'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'ui', 'index.html'), 'utf8');
const py = fs.readFileSync(path.join(ROOT, 'main.py'), 'utf8');
let bad = 0;
const fail = (m) => { bad++; console.log('  ❌ ' + m); };
const ok = (m) => console.log('  OK  ' + m);

// ① script 블록 문법
let m, i = 0;
const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
while ((m = re.exec(html)) !== null) {
  i++;
  const line = html.slice(0, m.index).split('\n').length;
  try { new vm.Script(m[1], { filename: `block${i}@${line}` }); }
  catch (e) { fail(`script #${i} (line ${line}): ${e.message}`); }
}
if (!bad) ok(`script 블록 ${i}개 문법 정상`);

// ② 톤 목록: STYLE_DEFAULTS ↔ #imgStyle option ↔ IC_STYLE
const styles = [...py.matchAll(/^    "(\w+)": """/gm)].map(x => x[1]);
const sel = html.match(/<select id="imgStyle">([\s\S]*?)<\/select>/);
const opts = sel ? [...sel[1].matchAll(/<option value="(\w+)"/g)].map(x => x[1]).filter(v => v !== 'auto') : [];
const icm = html.match(/const IC_STYLE\s*=\s*\[([\s\S]*?)\]\]/);   // 배열 끝은 `]]`
const ics = icm ? [...icm[1].matchAll(/\['(\w+)'/g)].map(x => x[1]).filter(v => v !== 'auto') : [];
const diff = (a, b) => a.filter(x => !b.includes(x));
if (!styles.length) fail('STYLE_DEFAULTS 를 찾지 못했다');
for (const [name, list] of [['#imgStyle option', opts], ['IC_STYLE', ics]]) {
  const miss = diff(styles, list), extra = diff(list, styles);
  const dup = list.filter((x, n) => list.indexOf(x) !== n);
  if (miss.length || extra.length || dup.length)
    fail(`${name}: 누락 ${JSON.stringify(miss)} 잉여 ${JSON.stringify(extra)} 중복 ${JSON.stringify(dup)}`);
  else ok(`${name} — 톤 ${list.length}개 일치`);
}

// ③ 주석 셀렉트 값이 백엔드 기대값과 같은가
const pick = (id) => {
  const s = html.match(new RegExp(`<select id="${id}"[\\s\\S]*?<\\/select>`));
  return s ? [...s[0].matchAll(/<option value="([^"]*)"/g)].map(x => x[1]) : null;
};
const eq = (a, b) => a && a.length === b.length && a.every(x => b.includes(x));
// 기대값을 하드코딩하면 백엔드에 모드가 늘 때마다 테스트가 거짓 실패한다 (glow 추가 때 그랬다)
// → ANNOTATION_MODES 를 main.py 에서 읽어 비교한다. UI 는 여기에 '없음'('')만 더한다.
const annoModes = [...((py.match(/ANNOTATION_MODES\s*=\s*\{([^}]*)\}/) || [, ''])[1])
  .matchAll(/"(\w+)"/g)].map(x => x[1]);
if (!annoModes.length) fail('ANNOTATION_MODES 를 찾지 못했다');
else if (!eq(pick('imgAnno'), ['', ...annoModes]))
  fail(`#imgAnno 값 불일치: UI=${JSON.stringify(pick('imgAnno'))} 백엔드=${JSON.stringify(annoModes)}`);
else ok(`#imgAnno = ANNOTATION_MODES(${annoModes.length}) + 없음`);
if (!eq(pick('vidAnno'), ['', 'auto', 'draw', 'animate'])) fail(`#vidAnno 값 불일치: ${JSON.stringify(pick('vidAnno'))}`);
else ok('#vidAnno = VIDEO_ANNO_MODES + auto/없음');
const colors = [...py.matchAll(/^    "(\w+)": \("/gm)].map(x => x[1]);
const csel = pick('imgAnnoColor');
if (csel && !['auto', ...colors.filter(c => ['red', 'cyan', 'amber', 'lime', 'white'].includes(c))]
    .every(v => csel.includes(v))) fail(`#imgAnnoColor 값 누락: ${JSON.stringify(csel)}`);
else ok('#imgAnnoColor = ANNO_COLORS + auto');

// ④ 컷 payload 가 주석에 필요한 필드를 보내는가
for (const fn of ['icPayload', 'vidPayload']) {
  const f = html.match(new RegExp(`function ${fn}\\(c\\)\\{[\\s\\S]*?\\n\\}`));
  if (!f) { fail(`${fn} 를 찾지 못했다`); continue; }
  const need = ['focus_en', 'measure_en', 'beat'];
  const miss = need.filter(k => !f[0].includes(k));
  if (miss.length) fail(`${fn}: ${miss.join(', ')} 누락 — 주석이 한 컷도 안 나온다`);
  else ok(`${fn} — focus_en·measure_en·beat 전달`);
}

// ⑤ 강조 상한이 UI 로 이어지는가.
// 백엔드 cap_anno_cuts 는 넘치는 컷에 anno='none' 을 달아 보낸다 — renderCuts 가 그걸
// annoSel 로 받지 않으면 카드가 '전역 따름'으로 그려지고 상한이 조용히 무효가 된다.
const rc = html.match(/window\.renderCuts\s*=\s*d\s*=>\s*\{[\s\S]*?\n\}/);
if (!rc) fail('renderCuts 를 찾지 못했다');
else if (!/annoSel\s*:\s*c\.anno/.test(rc[0]))
  fail('renderCuts 가 백엔드 anno 를 annoSel 로 받지 않는다 — 강조 상한이 무효가 된다');
else ok('renderCuts — 강조 상한(anno=none)이 컷 카드로 이어짐');

// 컷 payload 가 anno 를 실어야 백엔드가 컷별 설정을 본다 (icPayload=이미지, vidPayload=영상)
for (const [fn, re2] of [['icPayload', /anno\s*:\s*c\.annoSel/], ['vidPayload', /vanno\s*:/]]) {
  const f = html.match(new RegExp(`function ${fn}\\(c\\)\\{[\\s\\S]*?\\n\\}`));
  if (f && !re2.test(f[0])) fail(`${fn}: 컷별 주석 설정을 백엔드로 안 보낸다`);
  else if (f) ok(`${fn} — 컷별 주석 설정 전달`);
}

// 0(제한 없음)은 falsy 라 `||` 기본값을 쓰면 사용자의 선택이 매번 되돌아간다
if (/annoMax'\)\.value\s*=\s*String\([^)]*\|\|/.test(html))
  fail("#annoMax 초기화에 `||` 기본값 — '제한 없음'(0) 선택이 유지되지 않는다");
else ok('#annoMax — 0(제한 없음)이 기본값으로 덮이지 않음');

console.log(bad ? `\n❌ ${bad}건 실패` : '\n✅ 전 항목 통과');
process.exit(bad ? 1 : 0);
