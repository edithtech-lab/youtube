"""영상 주석 종류 자동 선택 + 훅 수치 예외 검증."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 콘솔이 cp949 여도 ✅/❌ 가 안 깨지게
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

BAD = 0
HOOK_M = {"style": "docu3d", "beat": "hook", "focus_en": "the reef", "measure_en": "20km"}
HOOK_NO = {"style": "docu3d", "beat": "hook", "focus_en": "", "measure_en": ""}
CLOSE_M = {"style": "docu3d", "beat": "closing", "focus_en": "the tower", "measure_en": "120Y"}
SOLU = {"style": "docu3d", "beat": "solution", "focus_en": "the joint", "measure_en": ""}

for name, cut, want in [("훅+수치", HOOK_M, True), ("훅 수치없음", HOOK_NO, False),
                        ("마무리+수치", CLOSE_M, False), ("해법", SOLU, True)]:
    got = bool(M.annotation_block(M.anno_for_cut("auto", cut, "full"), cut))
    ok = got == want
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} 주석 {name:12s} → {'있음' if got else '없음'} (기대 {'있음' if want else '없음'})")

print()
for name, img_anno, has_img, want in [
        ("이미지 주석 없음 + 이미지 O", "", True, "draw"),
        ("이미지 주석 auto + 이미지 O", "auto", True, "animate"),
        ("이미지 주석 full + 이미지 O", "full", True, "animate"),
        ("이미지 주석 auto + 이미지 X", "auto", False, "draw")]:
    got = M._video_anno_kind(img_anno, SOLU, has_img)
    ok = got == want
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} {name:26s} → {got:8s} (기대 {want})")

# 주석 대상이 아닌 컷은 이미지 주석을 켜도 draw (이미지에도 안 그려졌으니)
got = M._video_anno_kind("auto", HOOK_NO, True)
ok = got == "draw"
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} {'훅(주석 대상 아님)':26s} → {got:8s} (기대 draw)")

# 컷별 '이 컷은 없음'이면 이미지가 깨끗하므로 draw (전역 auto 여도 컷별이 이긴다)
for percut, want in (("none", "draw"), ("full", "animate"), ("", "animate")):
    got = M._video_anno_kind("auto", dict(SOLU, anno=percut), True)
    ok = got == want
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} {'컷별 anno=' + (percut or '(없음)'):26s} → {got:8s} (기대 {want})")

# 영상에는 수치를 새기지 않는다 — 720p 6초에서 작은 글자가 뭉개진다 (2026-08-06 실측)
print()
for m in ("draw", "animate"):
    L = M.video_anno_line(m, HOOK_M, "auto")
    ok = bool(L) and '"20km"' not in L and "20km" not in L and "cyan" in L
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} 영상 {m:8s} 수치없음={'20km' not in L} 시안={'cyan' in L}")
# 이미지 쪽은 그대로 수치를 새긴다
blk = M.annotation_block("full", HOOK_M)
ok = '"20km"' in blk
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 이미지 full  수치 새김={ok}")

print(f"\n{'❌ ' + str(BAD) + '건 실패' if BAD else '✅ 전 케이스 통과'}")
