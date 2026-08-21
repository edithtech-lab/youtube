"""강조 도구 4종 검사 — 컷이 말하는 논리에 맞는 도구가 골라지는가.

레퍼런스 채널 47컷 실측(2026-08-11): 강조는 "이걸 보세요"가 아니라 "이게 이렇게 됩니다"를
그린다. 화살표(움직임)·X(기각)·영역(구역)·HUD(치수)가 그 도구다. 이 파일이 막는 실패:
 ① 분해기가 고른 종류가 무시되고 전부 HUD 로 나온다
 ② 도구가 섞인다 (화살표 컷에 치수선·그리드가 따라붙음)
 ③ 라벨(글자)이 영상에서 새로 그려진다 — 720p 에서 뭉개진다
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


def cut(kind="", focus="the water rising into the basement", label="", measure="",
        shot="close", style="docu3d", beat="solution"):
    return {"no": 1, "style": style, "beat": beat, "shot": shot, "focus_en": focus,
            "measure_en": measure, "anno": "", "anno_kind": kind, "anno_label": label,
            "subject_en": "a basement wall", "motion": ""}


api = M.Api.__new__(M.Api)
CFG = {"img_anno_color": "auto", "img_style_override": {}, "img_anno": "auto"}
# 이미지·영상 문구가 같은 도구를 가리키는지 — 표현이 달라 마커를 따로 둔다
MARK = {"arrow": ("arrow", "arrow"),
        "reject": (" X ", " X "),
        "zone": ("outline encloses", "outline draws itself around"),
        "glow": ("holographic overlay", "holographic overlay"),
        # hud 는 measure 의 옛 이름 — 2026-08-18 부터 목록에서 빠지고 별칭만 남았다.
        # 판정이 measure 로 나오는 게 정상이라 ① 루프에서 빼고 아래 별칭 검사로 대신한다.
        # 수치 없는 measure 는 2026-08-19 부터 링으로 강등된다 (예전엔 윤곽선).
        "measure": ("ring is drawn", "technical HUD")}

print("=== ① 분해기가 고른 종류가 그대로 그려지는가")
# hud 는 옛 이름 — 옛 컷 JSON 이 와도 measure 로 읽혀야 한다 (2026-08-18 별칭화)
_g = M.anno_kind_for_cut(cut("hud"))
ok("hud(옛 이름) → measure 별칭") if _g == "measure" else bad(f"hud 별칭 판정이 {_g}")
for k, (mi, mv) in MARK.items():
    c = cut(k)
    got = M.anno_kind_for_cut(c)
    blk = M.annotation_block("full", c, "auto")
    if got != k:
        bad(f"{k}: 판정이 {got}")
    elif k in M.ANNO_IMAGE_SKIP:
        # 영상 전용 도구 — 이미지에는 **비어야** 맞다. 비어야 _video_anno_kind 가
        # 깨끗한 시작 프레임을 보고 'draw'(영상에서 새로 그림)로 간다 (2026-08-21).
        if blk:
            bad(f"{k}: 영상 전용인데 이미지 문구가 나왔다 — {blk[:70]}")
        else:
            ok(f"{k:6s} → 이미지 비움 OK (영상 전용)")
    elif mi not in blk:
        bad(f"{k}: 이미지 문구가 그 도구가 아니다 — {blk[:70]}")
    else:
        ok(f"{k:6s} → 이미지 OK")
    line = M.video_anno_line("draw", c, "auto")
    if not line:
        bad(f"{k}: 영상 문구가 비었다")
    elif mv not in line:
        bad(f"{k}: 영상 문구가 그 도구가 아니다 — {line[:70]}")
    else:
        ok(f"{k:6s} → 영상 OK")

print("\n=== ② 도구가 섞이지 않는가 (화살표 컷에 치수선·그리드가 따라붙으면 안 된다)")
for k in ("arrow", "reject", "zone"):
    c = cut(k, measure="45 m", shot="wide")     # 수치·와이드여도 고른 도구를 지켜야 한다
    blk = M.annotation_block("full", c, "auto")
    leak = [w for w in ("dimension line", "measurement grid", "technical HUD") if w in blk]
    if leak:
        bad(f"{k}: HUD 요소가 섞였다 {leak}")
    else:
        ok(f"{k:6s} — 수치·와이드에도 도구 유지, HUD 요소 없음")

print("\n=== ③ 라벨은 이미지에만 — 영상은 '유지'만 시킨다")
# ⚠ 예전엔 arrow 로 쟀는데 arrow 가 ANNO_IMAGE_SKIP(영상 전용)에 들어가면서 이미지가
# 비게 됐다 (2026-08-21). 라벨을 굽는 도구 중 하나로 바꾼다 — zone 은 그대로 이미지에 굽는다.
c = cut("zone", label="Water Up")
blk = M.annotation_block("full", c, "auto")
ok('이미지에 라벨이 새겨짐') if '"Water Up"' in blk else bad("이미지에 라벨이 안 새겨졌다")
if '"Water Up"' in M.video_anno_line("draw", c, "auto"):
    bad("영상 강조 문구가 라벨을 새로 그리려 한다 (720p 에서 뭉개진다)")
else:
    ok("영상 강조 문구에는 라벨이 없음")
# shape 모드는 '글자 없음' — 라벨도 빼야 한다
if '"Water Up"' in M.annotation_block("shape", c, "auto"):
    bad("shape 모드인데 라벨이 들어갔다")
else:
    ok("shape 모드 — 라벨 없음")
# I2V 는 이미지에 구워진 라벨을 유지해야 한다
mp = api._build_motion_prompt.__get__(api)(CFG, c, has_image=True, tempo="calm",
                                           audio="room", vanno="draw", vcolor="auto")
if "Water Up" not in mp:
    bad("I2V 가 이미지의 라벨을 유지하라고 하지 않는다 — 모델이 지운다")
elif "No letters, digits or words." in mp:
    bad("라벨 유지와 전면 텍스트 금지가 한 프롬프트에 공존한다 (정면충돌)")
else:
    ok("I2V — 라벨 유지 절이 붙고 금지문이 좁혀짐")

print("\n=== ③-b 분할 비교(versus) — 두 면·두 라벨·고정 카메라")
V = dict(cut("versus", focus="the same front actually built of brick under plaster"),
         compare_en="the temple front as everyone pictures it, solid white marble",
         anno_label="KNOWN / ACTUAL", shot="wide")
blk = M.annotation_block("full", V, "auto")
for want, msg in [("two stacked panels", "위아래 분할"), ("TOP panel", "위 면"),
                  ("BOTTOM panel", "아래 면")]:
    ok(msg) if want in blk else bad(f"{msg} 문구가 없다")
# 라벨은 접었다 — versus 는 글자 없이 간다 (versus_labels 가 anno_label 을 조용히 무시).
# 옛 습관으로 "KNOWN / ACTUAL" 이 들어와도 라벨 문구가 나오면 안 된다.
if "reads exactly" in blk:
    bad("접은 라벨이 다시 들어갔다 (versus 는 글자 없이)")
else:
    ok("라벨 무시 — 분할 비교는 글자 없이 간다")
if "reads exactly" in M.annotation_block("full", dict(V, anno_label="KNOWN"), "auto"):
    bad("슬래시 없는 라벨이 들어갔다")
else:
    ok("슬래시 없으면 라벨 없음")
if M.annotation_block("full", dict(V, compare_en=""), "auto"):
    bad("비교 대상이 없는데 분할 비교를 그린다")
else:
    ok("비교 대상 없으면 빈 문자열")
gotc = api._auto_camera(V)
ok(f"카메라 -> {gotc}") if gotc == "still" else bad(f"카메라가 {gotc} (분할 화면은 still 이어야 한다)")
ok("영상 모드 있음") if "versus_animate" in M.VIDEO_ANNO_MODES else bad("영상 모드에 versus 가 없다")

print("\n=== ④ 라벨 정규화 (한글·긴 문장은 못 쓴다)")
for raw, want in [("Steel Lid", "Steel Lid"), ("강철 뚜껑", ""), ("Dry Floor 바닥", "Dry Floor"),
                  # 관사·지시어는 걷어낸다 (2026-08-12) — 화면에서 글자수만 늘린다
                  ("a very long label that never ends", "very long"),
                  ("The Bronze Latch", "Bronze Latch"),
                  ("Relieving Chamber", "Relieving"),   # 16자 넘으면 단어 경계로 줄인다
                  ("", "")]:
    got = M.anno_label({"anno_label": raw})
    ok(f"{raw!r} → {got!r}") if got == want else bad(f"{raw!r} → {got!r} (기대 {want!r})")

print("\n=== ⑤ 종류를 안 고르면 예전 규칙대로 (하위 호환)")
for c, want in [(cut("", measure="45 m"), "measure"), (cut("", shot="wide"), "glow"),
                (cut(""), "measure"), (cut("", style="anime"), "manga")]:
    got = M.anno_kind_for_cut(c)
    ok(f"자동 판정 → {got}") if got == want else bad(f"자동 판정 {got} (기대 {want})")
if M.anno_kind_for_cut(cut("manga")) == "manga" and M.norm_style("docu3d") == "docu3d":
    bad("anime 가 아닌데 manga 를 직접 지정할 수 있다 (플랫 기호가 3D 컷에 나온다)")
else:
    ok("manga 는 anime 톤에서만 — 직접 지정 불가")

print(f"\n{'❌ 문제 ' + str(BAD) + '건' if BAD else '✅ 전 항목 통과'}")
sys.exit(1 if BAD else 0)
