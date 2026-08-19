# -*- coding: utf-8 -*-
"""docs/_현황.md 를 main.py 에서 다시 뽑는다.
#
# 왜 자동인가:
#   톤·카메라·리빌·모델·단가는 거의 매주 바뀐다. 손으로 적어두면 반드시 썩고,
#   썩은 목록은 없는 것보다 나쁘다 — 그걸 믿고 작업하기 때문이다.
#   (실제로 2026-08-14 에 "카메라 26종" 이라고 적힌 문서를 보고 작업했는데 그날 27종이 됐다)
#
# 언제 도나:
#   배포본_만들기.ps1 이 빌드 직전에 부른다. 손으로 돌릴 일은 없다.
#   직접 돌리려면:  python docs/_현황_뽑기.py
#
# 여기에 넣지 말 것:
#   '왜 그렇게 짰는가' 는 넣지 마라. 그건 01~05 서술문서와 코드 주석의 몫이다.
#   여기는 오직 "지금 값이 무엇인가" 만 적는다.
"""
import os
import sys
import io

# 빌드는 cp949 콘솔에서 돈다 — 여기서 UnicodeEncodeError 로 죽으면
# 배포 스크립트가 "갱신 실패"로 판단한다 (2026-08-15 실측). 출력 인코딩을 먼저 못박는다.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import re
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["COLLECTOR_NO_UI"] = "1"
import main as M  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_현황.md")
L = []


def w(s=""):
    L.append(s)


def table(head, rows):
    w("| " + " | ".join(head) + " |")
    w("|" + "|".join(["---"] * len(head)) + "|")
    for r in rows:
        w("| " + " | ".join(str(c) for c in r) + " |")
    w()


# ── 헤더 ────────────────────────────────────────────────────────────
today = datetime.date.today().isoformat()
w("# 현황 — 지금 코드에 들어 있는 값")
w()
w("> ⚙ **이 파일은 자동 생성됩니다.** 고치지 마세요 — 다음 빌드에 덮어씁니다.")
w("> 값을 바꾸려면 `main.py` 를 고치고 `python docs/_현황_뽑기.py` 를 돌리세요.")
w(">")
w("> 생성 %s · main.py %d줄" % (today, len(io.open(M.__file__, encoding="utf-8").read().splitlines())))
w()

# ── 지침 ────────────────────────────────────────────────────────────
w("## 컷 분해 지침 (claude.ai 쪽)")
w()
try:
    api = M.Api()
    api._js = lambda *a, **k: None
    g = api.split_guide()
    g = g["text"] if isinstance(g, dict) else g
    # ⚠ 여기서 따로 해시를 계산하면 안 된다. 앱이 지침 첫 줄에 박아 보내는 번호와
    #   달라져서, 사용자가 claude.ai 에 올린 지침이 최신인지 대조할 수 없게 된다.
    #   (2026-08-15 실제로 그렇게 틀린 번호를 알려준 적이 있다)
    m = re.search(r"지침 버전 ([0-9a-f]{8})", g)
    w("| 항목 | 값 |")
    w("|---|---|")
    w("| 버전 | **`%s`** ← 지침 첫 줄에 박히는 번호 |" % (m.group(1) if m else "?"))
    w("| 크기 | %s자 / %d줄 |" % ("{:,}".format(len(g)), len(g.splitlines())))
    w()
    w("**해시가 바뀌면 claude.ai 프로젝트 지식을 교체해야 합니다.** 앱만 새로 깔면 반영되지 않습니다 —")
    w("지침은 앱이 아니라 claude.ai 쪽에서 돌기 때문입니다. `[📋 지침 복사]` → 이전 것 삭제 후 붙여넣기.")
    w()
except Exception as e:
    w("(추출 실패: %r)" % (e,))
    w()

# ── 톤 ──────────────────────────────────────────────────────────────
w("## 톤 %d종" % len(M.STYLE_LABELS))
w()
src = set(M.SOURCE_STYLES)
for gname, keys in M.STYLE_GROUPS:
    w("**%s**" % gname)
    w()
    rows = []
    for k in keys:
        face = "기본(가림)"
        if k in ("game", "story3d", "toy3d"):
            face = "게임"
        elif k in ("greycast", "whitecast"):
            face = "마네킹"
        elif k == "anime":
            face = "만화"
        rows.append([
            "`%s`" % k,
            M.STYLE_LABELS.get(k, ""),
            "자료화면" if k in src else "",
            face,
            "O" if os.path.exists(os.path.join(os.path.dirname(OUT), "..", "ui", "tones", k + ".jpg")) else "**없음**",
        ])
    table(["id", "이름", "분류", "얼굴 정책", "샘플"], rows)

if M.STYLE_MIGRATE:
    w("구버전 id 자동 치환: " + " · ".join("`%s`→`%s`" % (a, b) for a, b in M.STYLE_MIGRATE.items()))
    w()

# ── 카메라 ──────────────────────────────────────────────────────────
w("## 카메라 %d종" % len(M.CAMERA_PRESETS))
w()
w("**강조(치수선·화살표)가 붙은 컷에서는 `CAMERA_LOUD` 표시된 워크가 `still`/`slowpush` 로 강등됩니다.**")
w("대상을 프레임 밖으로 밀어내거나 그래픽의 원근 고정을 깨뜨리기 때문입니다.")
w()
for gname, keys in M.CAMERA_GROUPS:
    w("**%s**" % gname)
    w()
    table(["id", "이름", "강조 컷"],
          [["`%s`" % k, M.CAMERA_LABELS.get(k, ""), "**CAMERA_LOUD**" if k in M.CAMERA_LOUD else "허용"] for k in keys])

w("자동 선택 (사용자가 `자동` 으로 두었을 때):")
w()
table(["기준", "매핑"],
      [["shot", " · ".join("%s→%s" % (a, b) for a, b in M.CAMERA_AUTO_SHOT.items())],
       ["beat", " · ".join("%s→%s" % (a, b) for a, b in M.CAMERA_AUTO_BEAT.items())],
       ["type", " · ".join("%s→%s" % (a, b) for a, b in M.CAMERA_AUTO_TYPE.items())]])

# ── 리빌 ────────────────────────────────────────────────────────────
w("## 리빌 %d종 (속을 열어 보이는 방식)" % len(M.REVEAL_LINES))
w()
table(["id", "이름"],
      [["`%s`" % k, M.REVEAL_LABELS.get(k, "")] for k in M.REVEAL_LINES])
w("빈 문자열 = 안 자름. 대부분의 컷이 여기에 해당합니다.")
w()

# ── 강조 ────────────────────────────────────────────────────────────
w("## 강조 %d종" % len(M.ANNO_KINDS))
w()
w("`" + "` · `".join(sorted(M.ANNO_KINDS)) + "`")
w()
if M.ANNO_ALIAS:
    w("별칭: " + " · ".join("`%s`→`%s`" % (a, b) for a, b in M.ANNO_ALIAS.items()))
w("양쪽 끝점이 필요한 종류(`from_en`/`to_en` 등): `" + "` · `".join(sorted(M.ANNO_SPAN_KINDS)) + "`")
w()

# ── 영상 모델 ───────────────────────────────────────────────────────
w("## 영상 모델과 길이")
w()
rows = []
for m in M.VIDEO_MODELS:
    eng = m.get("engine")
    if eng == "seedance":
        secs = " · ".join(str(x) for x in M.SEEDANCE_SECONDS)
    else:
        secs = " / ".join("%s→%s" % (r, ",".join(str(x) for x in v)) for r, v in M.VIDEO_SECS_BY_RES.items())
    rows.append(["`%s`" % m.get("id"), eng, m.get("label", ""), m.get("note", ""), secs])
table(["모델 id", "엔진", "이름", "메모", "쓸 수 있는 초"], rows)
w("**엔진마다 표가 다릅니다.** 베오 표를 시댄스에 적용하면 10·12초가 4초로 눌립니다 (2026-08-14 실제 버그).")
w()

# ── 이미지 모델 ─────────────────────────────────────────────────────
w("## 이미지 모델")
w()
table(["모델 id", "이름", "메모"], [["`%s`" % m.get("id"), m.get("label", ""), m.get("note", "")] for m in M.IMG_MODELS])

# ── 단가 ────────────────────────────────────────────────────────────
w("## 단가 (USD)")
w()
w("**이미지·기타**")
w()
table(["모델", "해상도", "USD/장"], [[("`%s`" % k[0]), k[1], v] for k, v in sorted(M.PRICE_USD.items())])
w("**영상**")
w()
table(["모델", "해상도", "USD/초"], [[("`%s`" % k[0]), k[1], v] for k, v in sorted(M.VIDEO_PRICE_USD.items())])
w("**LLM (컷 분해)**")
w()
table(["모델", "입력 USD/M", "출력 USD/M"], [[k, v[0], v[1]] for k, v in sorted(M.LLM_PRICE_USD.items())])

# ── 소스 위치 ───────────────────────────────────────────────────────
w("## 주요 함수 위치")
w()
w("행 번호는 이 파일을 뽑은 시점 기준입니다. 이름으로 찾으세요.")
w()
s = io.open(M.__file__, encoding="utf-8").read()
want = ["_generate_images", "_build_image_prompt", "annotation_block", "anno_for_cut",
        "_generate_videos_body", "_build_motion_prompt", "_auto_camera",
        "_source_video", "source_video_prompt",
        "_gen_seedance", "_gen_veo", "_archive_prev", "_archive_one",
        "norm_style", "is_cut_open", "is_graphic_cut", "split_guide", "_finish_split"]
rows = []
for name in want:
    m = re.search(r"\n\s*def %s\(" % re.escape(name), s)
    rows.append(["`%s`" % name, ("main.py:%d" % (s[:m.start()].count("\n") + 2)) if m else "—"])
table(["함수", "위치"], rows)

io.open(OUT, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("생성: %s (%d줄)" % (OUT, len(L)))


# ── 썩음 감시 ────────────────────────────────────────────────────────
# 손으로 쓴 문서에 "톤 19종" 같은 개수가 박혀 있으면 코드가 바뀔 때 조용히 거짓이 된다.
# 실제로 그렇게 썩은 문서 셋을 2026-08-15 에 찾아냈다(톤 14종·카메라 22종·리빌 5종).
# 개수를 아예 쓰지 말고 이 파일을 가리키게 하는 게 원칙이고, 여기서 어긴 곳을 잡는다.
# 빌드를 막지는 않는다 — 경고만 한다.
REAL = {"톤": len(M.STYLE_LABELS), "스타일": len(M.STYLE_LABELS),
        "카메라": len(M.CAMERA_PRESETS), "리빌": len(M.REVEAL_LINES),
        "강조": len(M.ANNO_KINDS)}
docs_dir = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(docs_dir)
targets = [os.path.join(root, "CLAUDE.md")]
targets += [os.path.join(docs_dir, f) for f in sorted(os.listdir(docs_dir))
            if f.endswith(".md") and f != os.path.basename(OUT)]
stale = []
for path in targets:
    if not os.path.exists(path):
        continue
    txt = io.open(path, encoding="utf-8").read()
    for mm in re.finditer(r"(톤|스타일|카메라|리빌|강조)\s*(\d+)\s*종", txt):
        kind, n = mm.group(1), int(mm.group(2))
        if REAL[kind] != n:
            stale.append("%s: '%s %d종' → 실제 %d종"
                         % (os.path.relpath(path, root), kind, n, REAL[kind]))
if stale:
    print("\n⚠ 문서에 박힌 개수가 코드와 다릅니다 — 고치거나 '_현황.md 참고'로 바꾸세요:")
    for x in stale:
        print("   " + x)
else:
    print("썩음 감시: 개수 불일치 없음")
