"""강조 몰입 규칙 검사 — 컷당 강조 하나 · 반복 애니메이션 없음 · 영상당 강조 컷 상한.

레퍼런스 채널의 강조는 '가끔 켜져서 눈길을 끄는 장치'다. 매 컷 켜지거나 한 컷에 여러 개가
그려지면 시선이 대사에서 떠나 화면 여기저기를 따라다닌다 — 이 파일은 그 세 가지를 막는다.
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M

BAD = 0


def bad(m):
    global BAD
    BAD += 1
    print("  ❌ " + m)


def ok(m):
    print("  OK  " + m)


def cut(no=1, style="docu3d", beat="solution", shot="close",
        focus="the stone tower base", measure=""):
    return {"no": no, "style": style, "beat": beat, "shot": shot,
            "focus_en": focus, "measure_en": measure, "anno": "",
            "subject_en": "a stone tower", "motion": ""}


DIM_IMG = "slim dimension line with fine end ticks"
# 2026-08-12 개정: 영상은 새로 안 그린다 — 이미 있는 치수선의 밝기만 바꾼다
DIM_VID = "slim dimension line already visible beside it brightens"
CONTOUR = "contour"

print("=== ① 컷당 강조 요소는 하나 (치수선은 수치를 얹을 때만)")
for mode, m, want_dim in [("shape", "", False), ("shape", "45 m", False),
                          ("full", "", False), ("full", "45 m", True)]:
    blk = M.annotation_block(mode, cut(measure=m), "auto")
    has = DIM_IMG in blk
    if CONTOUR not in blk:
        bad(f"이미지 {mode}/{m or '수치없음'}: 윤곽선이 없다")
    elif has != want_dim:
        bad(f"이미지 {mode}/{m or '수치없음'}: 치수선 {'있음' if has else '없음'} (기대 {want_dim})")
    else:
        ok(f"이미지 {mode:5s} 수치={m or '없음':6s} → 요소 {'윤곽선+치수선' if has else '윤곽선만'}")

for m, want_dim in [("", False), ("45 m", True)]:
    line = M.video_anno_line("draw", cut(measure=m), "auto")
    has = DIM_VID in line
    if has != want_dim:
        bad(f"영상 draw/{m or '수치없음'}: 치수선 {'있음' if has else '없음'} (기대 {want_dim})")
    else:
        ok(f"영상 draw  수치={m or '없음':6s} → 요소 {'윤곽선+치수선' if has else '윤곽선만'}")

print("\n=== ② 지면 그리드는 어느 컷에도 붙지 않는다 (2026-08-12 제거)")
# 조건이 shot=="wide" 하나뿐이라 실내·단면 와이드에도 바닥 원판이 깔렸다.
# 야외 측량 컷에만 어울리는 장치인데 shot 만으로는 그 조건을 가려낼 수 없어 걷어냈다.
for shot in ("close", "macro", "object", "screen", "cutaway", "wide"):
    img = "circular measurement grid" in M.annotation_block("shape", cut(shot=shot), "auto")
    vid = "circular measurement grid" in M.video_anno_line("draw", cut(shot=shot, measure="45 m"), "auto")
    if img or vid:
        bad(f"shot={shot}: 그리드가 아직 붙는다 (이미지={img} 영상={vid})")
    else:
        ok(f"shot={shot:8s} 그리드 없음")

print("\n=== ③ 반복 애니메이션 금지 — 켜지고 나면 멈춰 있어야 한다")
HOLD = ("no looping", "never flashes, strobes, loops")   # 문장 첫머리면 대문자라 lower() 로 본다
for mode in ("draw", "animate"):
    line = M.video_anno_line(mode, cut(), "auto").lower()
    if not any(h in line for h in HOLD):
        bad(f"영상 {mode}: '켜진 뒤 유지' 지시가 없다 — HUD 가 클립 내내 깜빡일 수 있다")
    else:
        ok(f"영상 {mode:8s} 유지 지시 있음")
for mode in ("draw", "animate"):
    line = M.video_anno_line(mode, cut(style="arch3d", shot="wide"), "auto")
    if "ignites" not in line and "holds steady" not in line:
        bad(f"영상 glow_{mode}: 발광 강조에 유지 지시가 없다")
    else:
        ok(f"영상 glow_{mode:6s} 유지 지시 있음")

print("\n=== ④ 영상당 강조 컷 상한 (약한 것부터 끈다)")
cuts = [cut(1, beat="hook", focus="", measure=""),
        cut(2, beat="context"),
        cut(3, beat="constraint"),
        cut(4, beat="solution", measure="45 m"),
        cut(5, beat="analogy"),
        cut(6, beat="pivot"),
        cut(7, beat="closing"),
        cut(8, beat="context")]
def live(cs):
    """실제 생성 경로대로 — 컷별 설정(anno)을 존중해 강조가 켜지는 컷"""
    return [c["no"] for c in cs
            if M.annotation_block(M.anno_for_cut(c.get("anno") or "auto", c, "shape"), c, "auto")]


before = live(cuts)
off = M.cap_anno_cuts(cuts, 3)
after = live(cuts)
print(f"  상한 전 강조 컷: {before} → 후: {after} (해제 {off}컷)")
if len(after) > 3:
    bad(f"상한 3인데 {len(after)}컷이 켜져 있다")
elif 4 not in after:
    bad("수치가 있는 4번 컷이 꺼졌다 — 수치는 강조 위에만 올라가므로 최우선이어야 한다")
elif not all(cuts[n - 1]["beat"] in M.ANNO_AUTO_BEATS or cuts[n - 1]["measure_en"] for n in after):
    bad(f"설명 비트가 아닌 컷이 남았다: {after}")
else:
    ok(f"상한 3 적용 — 수치 컷·설명 비트가 살아남음 {after}")

# 끈 컷은 문구를 잃지 않아야 한다 — 사용자가 셀렉트를 '자동'으로 되돌리면 그대로 복구된다
lost = [c["no"] for c in cuts if c.get("anno") == "none" and not c.get("focus_en")]
if lost:
    bad(f"꺼진 컷 {lost} 의 강조 대상 문구가 지워졌다 — 되살릴 수 없다")
else:
    ok("꺼진 컷도 강조 대상·수치 문구를 그대로 보존")
back = [c for c in cuts if c.get("anno") == "none"][0]
back["anno"] = "auto"                                    # 사용자가 카드에서 '자동'으로 되돌림
if not M.annotation_block(M.anno_for_cut("auto", back, "shape"), back, "auto"):
    bad(f"#{back['no']}: '자동'으로 되돌렸는데 강조가 복구되지 않는다")
else:
    ok(f"#{back['no']} '자동'으로 되돌리면 강조 복구됨")
back["anno"] = "none"

# 꺼진 컷은 이미지·영상 양쪽 다 무음이어야 한다
for c in cuts:
    if (c.get("anno") or "") != "none":
        continue
    vm = M.anno_for_cut(c.get("anno"), c, "draw")
    if M.annotation_block(M.anno_for_cut(c.get("anno"), c, "shape"), c, "auto") \
       or M.video_anno_line(vm, c, "auto"):
        bad(f"#{c['no']}: 꺼진 컷인데 강조 문구가 나온다")
else:
    ok("꺼진 컷은 이미지·영상 양쪽 다 무음")

if M.cap_anno_cuts(cuts, 3) != 0:
    bad("이미 상한을 맞춘 컷들을 다시 끄고 있다 (여러 번 불러도 결과가 같아야 한다)")
else:
    ok("두 번 불러도 결과 동일 (멱등)")

if M.cap_anno_cuts([cut(i) for i in range(1, 9)], 0) != 0:
    bad("anno_max=0 은 무제한이어야 한다")
else:
    ok("anno_max=0 → 무제한 (예전 동작 유지)")

print("\n=== ④-b 실제 생성 경로 — 배치 전역 설정과 컷별 'none' 이 함께 걸릴 때")
# main.py:4381 과 같은 식: anno_for_cut(cut['anno'] or 전역, cut, 'full')
for g in ("", "auto", "shape"):
    def img_on(c):
        return bool(M.annotation_block(M.anno_for_cut(c.get("anno") or g, c, "full"), c, "auto"))

    def vid_on(c):
        vg = "none" if c.get("anno") == "none" else g          # vidPayload 와 같은 규칙
        return bool(M.video_anno_line(M.anno_for_cut(vg, c, "draw"), c, "auto"))
    live_n = sum(1 for c in cuts if img_on(c))
    offc = [c["no"] for c in cuts if c.get("anno") == "none"]
    hit = [c["no"] for c in cuts if c.get("anno") == "none" and (img_on(c) or vid_on(c))]
    if hit:
        bad(f"전역={g or '없음'}: 꺼둔 컷 {hit} 에 강조가 다시 켜졌다")
    else:
        ok(f"전역={g or '없음':5s} → 꺼둔 컷 {offc} 은 계속 무음 (강조 {live_n}컷)")

print("\n=== ⑤ 강조는 대사가 짚는 그 대상에 — 화면에서 제일 큰 것에 걸리면 안 된다")
LOCK = "not the biggest or most prominent"
LOCK_IMG = "not the largest or most"
for mode in ("shape", "full", "glow"):
    blk = M.annotation_block(mode, cut(measure="45 m"), "auto")
    if LOCK_IMG not in blk and "not simply the biggest structure" not in blk:
        bad(f"이미지 {mode}: 강조 대상 잠금 문구가 없다 — 눈에 띄는 물체로 새어나간다")
    else:
        ok(f"이미지 {mode:5s} 대상 잠금 있음")
for mode, c in [("draw", cut()), ("animate", cut()),
                ("glow_draw", cut(style="arch3d", shot="wide")),
                ("glow_animate", cut(style="arch3d", shot="wide"))]:
    line = M.video_anno_line(mode.replace("glow_", ""), c, "auto")
    if LOCK not in line and "not simply the biggest structure" not in line:
        bad(f"영상 {mode}: 강조 대상 잠금 문구가 없다")
    else:
        ok(f"영상 {mode:13s} 대상 잠금 있음")

print("\n=== ⑥ 플랫 톤(illust·blueprint) 강조 시 네거티브 모순 없음")
api = M.Api.__new__(M.Api)
cfg = {"img_anno_color": "auto", "img_style_override": {}}
for s in ("illust", "blueprint"):
    full = api._build_prompt(cfg, cut(style=s), [], "shape")
    hard = "3D shading, gradients, drop shadows." in full
    if hard:
        bad(f"{s}: 강조가 붙었는데 '발광 전면 금지' 네거티브가 그대로다 (프롬프트 내부 충돌)")
    else:
        ok(f"{s:9s} 강조 시 완화판 네거티브 적용")
    plain = api._build_prompt(cfg, cut(style=s, focus=""), [], "shape")
    if "3D shading, gradients, drop shadows." not in plain:
        bad(f"{s}: 강조가 없는 컷인데 네거티브가 완화됐다 — 그림이 입체가 된다")
    else:
        ok(f"{s:9s} 강조 없으면 원래 FLAT 네거티브 유지")

print(f"\n{'❌ 문제 ' + str(BAD) + '건' if BAD else '✅ 전 항목 통과'}")
sys.exit(1 if BAD else 0)
