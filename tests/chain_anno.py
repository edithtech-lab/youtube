"""⛓ 체인 컷의 주석 이어받기 검증 — 앞 클립 끝 프레임에 HUD가 있으면 animate 로 살린다."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 콘솔이 cp949 여도 ✅/❌ 가 안 깨지게
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

BAD = 0
A = {"no": 5, "style": "docu3d", "beat": "solution", "focus_en": "the joint",
     "measure_en": "", "chain": False}
B = {"no": 6, "style": "docu3d", "beat": "solution", "focus_en": "the base",
     "measure_en": "", "chain": True}
NOFOCUS = {"no": 7, "style": "docu3d", "beat": "solution", "focus_en": "", "chain": True}


def kind(cut, start_name, prev_anno, img_anno=""):
    """_generate_videos_body 의 판정 로직을 그대로 재현한다."""
    chained = bool(cut.get("chain")) and start_name and "_chain_" in os.path.basename(start_name)
    return ("animate" if (chained and prev_anno)
            else M._video_anno_kind(img_anno, cut, bool(start_name)))


CASES = [
    ("첫 컷 (자기 이미지)", A, "05_x.jpg", False, "draw"),
    ("체인 + 앞 컷이 HUD 그림", B, "_chain_06.png", True, "animate"),
    ("체인 + 앞 컷은 깨끗", B, "_chain_06.png", False, "draw"),
    ("체인인데 앞 클립 없어 자기 이미지", B, "06_x.jpg", True, "draw"),
]
for name, cut, sn, prev, want in CASES:
    got = kind(cut, sn, prev)
    ok = got == want
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} {name:28s} → {got:8s} (기대 {want})")

# focus 가 없으면 어떤 kind 든 결국 주석이 안 나온다
line = M.video_anno_line(M.anno_for_cut("auto", NOFOCUS, "animate"), NOFOCUS, "auto")
ok = not line
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} {'focus 없는 체인 컷':28s} → {'주석 없음' if ok else '주석 나옴'}")

# prev_anno 는 '실제로 문구가 붙었는가'로 갱신돼야 한다 (모드만 보고 판단하면 안 됨)
for cut, want in ((A, True), (NOFOCUS, False)):
    vm = M.anno_for_cut("auto", cut, "draw")
    got = bool(M.video_anno_line(vm, cut, "auto"))
    ok = got == want
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} prev_anno #{cut['no']} 갱신 → {got} (기대 {want})")

print(f"\n{'❌ ' + str(BAD) + '건 실패' if BAD else '✅ 전 케이스 통과'}")
