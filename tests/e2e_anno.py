"""프론트 payload 계층까지 포함한 실제 경로 검증 (직접 dict 주입 금지)."""
import sys, os, json, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 콘솔이 cp949 여도 ✅/❌ 가 안 깨지게
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

SC = """여기 육지에서 20km나 떨어진 바다 한가운데 암초가 있습니다.
밤이 되면 보이지도 않는 이 바위에 배들이 밥 먹듯이 부딪혀 가라앉았죠.
근데 집채만 한 파도가 시도 때도 없이 때리는 곳에 대체 어떻게 세워요?
처음엔 나무로 등대를 지어봤는데 5년 만에 폭풍이 통째로 쓸어갔고요.
돌덩이 하나하나를 제비꼬리 모양으로 깎아 퍼즐처럼 서로 꽉 맞물리게 했습니다.
파도가 아무리 때려도 옆에 돌을 붙잡고 있으니 뜯어낼 수가 없는 거죠.
그렇게 세워진 돌 등대는 120년 넘게 파도를 이겨냈습니다."""

api = M.Api()
out = []
api._emit = lambda js: out.append(js)
api._split_script({"script": SC, "nCuts": "자동"})
cuts = json.loads(re.search(r"renderCuts\((.*)\)$", out[-1], re.S).group(1))["cuts"]

from collections import Counter
print("=== 분해 결과")
tone = Counter()
for c in cuts:
    tone[c.get("style") or "-"] += 1
    f = (c.get("focus_en") or "")
    print(f" #{c['no']:2d} {(c.get('style') or '-'):9s} [{(c.get('beat') or '-'):10s}] "
          f"{'🎯 ' + f[:46] if f else '— 주석없음'}  m={c.get('measure_en') or '-'}")
print(" 톤 분포:", dict(tone))


def ic_payload(c):   # ui/index.html 의 icPayload 와 같은 필드만 남긴다
    return {"no": c["no"], "scene_ko": c.get("scene_ko"), "subject_en": c.get("subject_en"),
            "place_en": c.get("place_en"), "shot": c.get("shot"), "type": c.get("type"),
            "mode": c.get("mode"), "style": c.get("style") or "docu3d",
            "beat": c.get("beat") or "", "focus_en": c.get("focus_en") or "",
            "measure_en": c.get("measure_en") or "", "anno": ""}


cfg = M.load_config()
cfg["img_anno_color"] = "auto"
BAD = 0
print("\n=== 이미지 프롬프트 (배치=auto, 컷별=auto 두 경로)")
for c in cuts:
    for percut in ("", "auto"):
        p = ic_payload(c); p["anno"] = percut
        full = api._build_prompt(cfg, p, [], M.anno_for_cut(p["anno"] or "auto", p))
        # 특정 문구("holographic technical HUD")로 찾으면 문구 개정 때마다 낡는다 —
        # 실제 강조 블록의 첫 줄이 프롬프트에 들어갔는지로 판정한다 (도구 무관)
        _blk = M.annotation_block(M.anno_for_cut(p["anno"] or "auto", p), p,
                                  cfg.get("img_anno_color") or "auto")
        hud = bool(_blk) and _blk.splitlines()[0] in full
        want = "MARKS described above are wanted" in full
        # 훅은 수치가 있으면 예외로 켜진다 — 그 경우는 '금지 컷'으로 세지 않는다
        skip = ((c.get("beat") or "") in M.ANNO_SKIP_BEATS
                and not (c.get("beat") == "hook" and (c.get("measure_en") or "").strip()))
        if percut == "":
            print(f" #{c['no']:2d} HUD={'O' if hud else '.'} negWant={'O' if want else '.'} "
                  f"cyan={'O' if '#22D3EE' in full else '.'} red={'O' if '#FF2D2D' in full else '.'}")
        if hud != want:
            print("   ⚠ HUD/네거티브 불일치"); BAD += 1
        if hud and skip:
            print(f"   ⚠ 훅·마무리 컷({c['beat']})에 주석 (percut={percut!r})"); BAD += 1
        if hud and not (c.get("focus_en") or "").strip():
            print("   ⚠ focus 없는데 주석"); BAD += 1

print("\n=== 영상 프롬프트")
for c in cuts:
    p = ic_payload(c)
    vm = M.anno_for_cut("auto", p, "draw")
    line = M.video_anno_line(vm, p, "auto")
    la = M.video_anno_line(vm, p, "amber")
    col = "cyan" if "cyan" in line else ("red" if "red" in line else "-")
    print(f" #{c['no']:2d} vanno={vm or '-':6s} auto→{col:5s} amber→{'O' if 'amber' in la else '-'} "
          f"라벨={'O' if chr(34) in line else '-'}")
    # 영상에는 수치를 안 새긴다 — 720p 6초에서 작은 글자가 뭉개진다 (2026-08-06)
    if line and chr(34) in line:
        print("   ⚠ 영상 프롬프트에 수치 라벨이 들어갔다"); BAD += 1

print("\n=== 등록부 점검")
allg = [x for _, ks in M.STYLE_GROUPS for x in ks]
print(" STYLE_GROUPS 누락:", [k for k in M.STYLE_DEFAULTS if k not in allg] or "없음")
print(" STYLE_GROUPS 유령:", [k for k in allg if k not in M.STYLE_DEFAULTS] or "없음")
print(" STYLE_LABELS 누락:", [k for k in M.STYLE_DEFAULTS if k not in M.STYLE_LABELS] or "없음")
print(" ANNO_COLOR_BY_STYLE 유효색:",
      all(v in M.ANNO_COLORS for v in M.ANNO_COLOR_BY_STYLE.values()))
print(f"\n{'❌ 문제 ' + str(BAD) + '건' if BAD else '✅ 전 항목 통과'}")
