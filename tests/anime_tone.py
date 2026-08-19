"""만화 요약(anime) 톤 검사 — 만화 기호 강조 · 캐릭터 시트 · 저작권 잠금 · 영상 룩 유지.

이 톤의 실패 모드는 셋이다:
 ① 플랫 셀 그림 위에 계측 HUD·발광 오버레이가 뜬다 (다른 톤의 강조가 새어들어옴)
 ② 컷마다 인물이 딴 사람이 된다 (캐릭터 시트 미적용)
 ③ 원작 그림체·유니폼·엠블럼이 그대로 재현된다 (2차 창작 선을 넘음)
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


SHEET = r"C:\sheets\slam.png"
api = M.Api.__new__(M.Api)
CFG = {"img_anno_color": "auto", "img_style_override": {}, "char_sheet": SHEET}


def cut(no=1, style="anime", beat="solution", shot="close",
        focus="the red-haired boy pushing himself off the floor", measure="", chars=None):
    return {"no": no, "style": style, "beat": beat, "shot": shot, "focus_en": focus,
            "measure_en": measure, "anno": "", "chars": chars if chars is not None else ["A"],
            "subject_en": "a red-haired cartoon boy on a gym floor", "place_en": "a school gym",
            "motion": ""}


print("=== ① 등록 정합")
for name, cond in [
        ("STYLE_DEFAULTS 에 anime", "anime" in M.STYLE_DEFAULTS),
        ("STYLE_LABELS 에 anime", "anime" in M.STYLE_LABELS),
        ("STYLE_GROUPS 에 anime", any("anime" in ks for _, ks in M.STYLE_GROUPS)),
        ("NEG_BY_STYLE 에 anime", M.NEG_BY_STYLE.get("anime") is M.NEGATIVE_ANIME),
        ("강조 자동 대상에서 제외", "anime" not in M.ANNO_AUTO_STYLES)]:
    ok(name) if cond else bad(name)

print("\n=== ② 강조는 만화 기호로 — HUD·발광이 새어들면 안 된다")
LEAK = ("holographic", "hairline", "neon bloom", "dimension line", "measurement grid",
        "translucent", "luminous")


def leaks(txt):
    """HUD·발광 문구가 '요구'로 들어왔는지. 만화 기호 템플릿은 같은 단어를 **금지문**으로
    쓰므로(never glowing, never translucent) 그 맥락은 유입이 아니다.
    문장부호까지 통째로 지운다 — 리터럴 치환은 쉼표/마침표 차이로 조용히 빗나간다."""
    import re
    t = re.sub(r"never (glowing|translucent|a digital overlay)[,.]?\s*", "", txt)
    return [w for w in LEAK if w in t]
for shot in ("close", "wide", "macro"):
    for mode in ("shape", "full", "glow", "auto"):
        c = cut(shot=shot, measure="45 m")
        if M.anno_kind_for_cut(c) != "manga":
            bad(f"shot={shot} anno={mode}: 강조 종류가 manga 가 아니다")
            continue
        blk = M.annotation_block(mode, c, "auto")
        leaked = leaks(blk)
        if leaked:
            bad(f"shot={shot} anno={mode}: HUD/발광 문구 유입 {leaked}")
    ok(f"shot={shot:6s} — 전 모드에서 만화 기호만 (HUD·발광 없음)")
# 컷별로 glow 를 강제해도 anime 는 만화 기호여야 한다 (플랫 그림 위 홀로그램 방지)
if M.anno_kind_for_cut(dict(cut(), anno="glow")) != "manga":
    bad("컷별 glow 강제가 anime 톤을 뚫었다")
else:
    ok("컷별 glow 강제해도 만화 기호 유지")
# 영상도 같은 규칙
for mode in ("draw", "animate"):
    line = M.video_anno_line(mode, cut(), "auto")
    leaked = leaks(line)
    if not line:
        bad(f"영상 {mode}: 강조 문구가 비었다")
    elif leaked:
        bad(f"영상 {mode}: HUD/발광 문구 유입 {leaked}")
    elif "cartoon emphasis marks" not in line:
        bad(f"영상 {mode}: 만화 기호 문구가 아니다")
    else:
        ok(f"영상 {mode:8s} — 만화 기호")
# 만화 기호는 붙고 나면 멈춘다 (움직이면 그림이 지저분해진다)
for mode in ("draw", "animate"):
    line = M.video_anno_line(mode, cut(), "auto")
    if "no looping" not in line and "never multiply, drift, blink" not in line:
        bad(f"영상 {mode}: 정지 유지 지시가 없다")
    else:
        ok(f"영상 {mode:8s} — 붙은 뒤 정지")

print("\n=== ③ 캐릭터 시트 — 지시가 톤 레퍼런스와 뒤바뀌지 않는가")
p = api._build_prompt(CFG, cut(chars=["A", "B"]), [SHEET], "auto")
if "character sheet" not in p:
    bad("시트가 있는데 CHAR_SHEET_LINE 이 안 붙었다")
elif "Do not copy their subject" in p:
    bad("시트 컷에 STYLE_REF_LINE(피사체 복사 금지)이 함께 붙었다 — 지시 충돌")
elif "character A and character B" not in p:
    bad("등장인물 지목이 빠졌다")
else:
    ok("시트 컷 — 캐릭터 지시 + 인물 지목, 톤 레퍼런스 문구 없음")
p2 = api._build_prompt(CFG, cut(style="illust"), [r"C:\refs\tone.png"], "auto")
if "character sheet" in p2 or "Do not copy their subject" not in p2:
    bad("다른 톤인데 캐릭터 시트 지시가 새어들었다")
else:
    ok("다른 톤 — 기존 톤 레퍼런스 문구 유지")
p3 = api._build_prompt(dict(CFG, char_sheet=""), cut(), [], "auto")
if "character sheet" in p3:
    bad("시트가 없는데 시트 지시가 붙었다")
elif "hand-drawn Japanese cartoon" not in p3:
    bad("시트 없이는 톤 자체가 깨진다 — 폴백이 안 된다")
else:
    ok("시트 없어도 톤은 정상 동작 (선택 사항)")
for raw, want in [(["A", "B"], ["A", "B"]), ("A, b /c", ["A", "B", "C"]),
                  ([], []), ("", []), (["강백호"], []), (["A", "A", "B"], ["A", "B"])]:
    got = M.sheet_chars({"chars": raw})
    ok(f"chars {raw!r} → {got}") if got == want else bad(f"chars {raw!r} → {got} (기대 {want})")

print("\n=== ④ 저작권 — 원작 복제 잠금")
p = api._build_prompt(CFG, cut(), [SHEET], "auto")
for name, kw in [("실존 인물 닮기 금지", "never resemble any real person"),
                 ("원작 디자인 복제 금지", "any existing manga, anime, game or film"),
                 ("유니폼·엠블럼 금지", "emblems"),
                 ("얼굴 숨기기는 풀림 (인물 톤)", None)]:
    if kw is None:
        ok(name) if M.FACE_HIDE not in p else bad("anime 인데 얼굴 숨기기가 걸려 있다")
    elif kw in p:
        ok(name)
    else:
        bad(f"{name} — 문구가 프롬프트에 없다")
if M.CHAR_SHEET_PROMPT.count("original characters") < 1 or "emblems" not in M.CHAR_SHEET_PROMPT:
    bad("시트 생성 프롬프트에 저작권 잠금이 없다")
else:
    ok("시트 생성 프롬프트에도 저작권 잠금")

print("\n=== ⑤ 영상 룩 유지 — 정교한 애니·3D 로 흐르지 않게")
mp = api._build_motion_prompt.__get__(api)(
    CFG, cut(), has_image=True, tempo="calm", audio="room", vanno="", vcolor="auto")
if "flat cartoon drawing" not in mp:
    bad("I2V 에 anime 룩 잠금이 안 붙었다 — 실사·3D 로 드리프트한다")
else:
    ok("I2V — 플랫 만화 룩 잠금")
if "game physics engine" in mp:
    bad("anime 컷에 game 톤의 물리 무게감이 붙었다")
else:
    ok("game 톤 물리 절이 섞이지 않음")
mp2 = api._build_motion_prompt.__get__(api)(
    CFG, cut(), has_image=False, tempo="calm", audio="room", vanno="", vcolor="auto")
if "flat cartoon drawing" in mp2:
    bad("이미지가 없는데(T2V) 시작 프레임 유지 절이 붙었다")
else:
    ok("T2V — 시작 프레임 유지 절 없음")

print("\n=== ⑥ 강조 상한과의 상호작용")
cuts = [cut(i, beat=b) for i, b in enumerate(
    ["hook", "context", "constraint", "solution", "analogy", "pivot"], 1)]
off = M.cap_anno_cuts(cuts, 2)
live = [c["no"] for c in cuts
        if M.annotation_block(M.anno_for_cut(c.get("anno") or "auto", c, "shape"), c, "auto")]
if len(live) > 2:
    bad(f"상한 2인데 {len(live)}컷이 켜져 있다 (anime 톤에서 상한이 안 먹는다)")
else:
    ok(f"상한 2 적용 — 만화 기호도 {live} 만 켜짐 (해제 {off}컷)")

print(f"\n{'❌ 문제 ' + str(BAD) + '건' if BAD else '✅ 전 항목 통과'}")
sys.exit(1 if BAD else 0)
