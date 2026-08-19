"""shape/full/none/auto 4개 모드가 실제로 다르게 동작하는지 + 컷별 오버라이드 경로."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 콘솔이 cp949 여도 ✅/❌ 가 안 깨지게
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

api, cfg = M.Api(), M.load_config()
cfg["img_anno_color"] = "auto"
BAD = 0

CUT = {"no": 1, "style": "docu3d", "shot": "close", "beat": "solution",
       "subject_en": "two granite blocks", "place_en": "a rock", "mode": "ai",
       "focus_en": "the dovetail joint", "measure_en": "120Y"}
NOFOCUS = dict(CUT, focus_en="", measure_en="20km")
HOOK = dict(CUT, beat="hook")               # 수치가 있는 훅 — 예외로 주석이 켜진다
HOOK_NM = dict(CUT, beat="hook", measure_en="")   # 수치 없는 훅 — 원칙대로 꺼진다

CASES = [
    ("전역 shape / 수치 있음", CUT, "", "shape", True, False),
    ("전역 full / 수치 있음", CUT, "", "full", True, True),
    ("전역 auto / 수치 있음", CUT, "", "auto", True, True),
    # 훅은 원칙적으로 꺼지지만 수치가 있으면 예외 — 첫 2초의 숫자가 시청자를 잡는다
    ("전역 auto / 훅 수치없음", HOOK_NM, "", "auto", False, False),
    ("전역 auto / 훅 수치있음", HOOK, "", "auto", True, True),
    ("전역 auto / focus 없음", NOFOCUS, "", "auto", False, False),
    ("컷별 none (전역 full)", CUT, "none", "full", False, False),
    ("컷별 shape (전역 없음)", CUT, "shape", "", True, False),
    ("컷별 auto / 훅 수치없음", HOOK_NM, "auto", "", False, False),
    ("컷별 full / 훅 컷", HOOK, "full", "", True, True),
]
for name, cut, percut, glob, want_hud, want_num in CASES:
    mode = M.anno_for_cut(percut or glob, cut, "full")
    p = api._build_prompt(cfg, cut, [], mode)
    # 2026-08-12 개정: "holographic technical HUD" 문구를 걷어내고 도면식 윤곽선으로 바꿈
    # 2026-08-19 개정: 수치를 안 새기는 경우는 윤곽선 대신 링 — 도형 존재 여부만 본다
    hud = ("contour is drawn" in p) or ("ring is drawn" in p)
    num = '"120Y"' in p or '"20km"' in p
    ok = (hud == want_hud) and (num == want_num)
    if not ok:
        BAD += 1
    print(f" {'OK ' if ok else '❌ '} {name:28s} → HUD={'O' if hud else '.'}(기대 "
          f"{'O' if want_hud else '.'}) 숫자={'O' if num else '.'}(기대 {'O' if want_num else '.'})")

# 영상: 컷별 none 이 실제로 끄는지
for percut, want in (("", True), ("none", False)):
    vm = M.anno_for_cut(percut or "auto", CUT, "draw")
    line = M.video_anno_line(vm, CUT, "auto")
    ok = bool(line) == want
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} 영상 vanno={percut or '(전역auto)':10s} → "
          f"{'주석 있음' if line else '주석 없음'}")

print(f"\n{'❌ ' + str(BAD) + '건 실패' if BAD else '✅ 전 케이스 통과'}")
