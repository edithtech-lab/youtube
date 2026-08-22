# -*- coding: utf-8 -*-
"""강조 도구 문서 생성기 — main.py 를 임포트해 실제 등록 상태를 뽑는다.

사용:  python docs/_강조도구_뽑기.py   (프로젝트 루트에서)
출력:  docs/06_강조도구.md

개수·키·조립 여부는 전부 코드에서 실시간으로 세므로 문서가 코드와 어긋나지 않는다.
한 줄 설명·필요 필드만 아래 표에 손으로 든다 — 도구를 추가하면 여기도 한 줄 추가할 것
(빠뜨리면 문서에 '설명 없음'으로 나와서 바로 티가 난다).
"""
import io, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

# 분류 · 한 줄 설명 · 필요 필드 · 영상에서 일어나는 일 (손으로 관리)
INFO = {
    # kind: (분류, 설명, 필요 필드, 영상 동작)
    "glow":      ("가리키기", "발광 — 대상 전체 점등", "focus_en",
                  "덮인 발광이 아주 느리게 숨쉬듯 밝기만 변함"),
    "outline":   ("가리키기", "윤곽선 — 여럿 중 이것", "focus_en",
                  "실루엣에 고정, 밝은 펄스가 윤곽 한 바퀴 후 정착"),
    "spotlight": ("가리키기", "스포트라이트 — 어둠 속 조명", "focus_en",
                  "빛 웅덩이가 제자리 유지, 은은한 일렁임만"),
    "marker":    ("가리키기", "마커 — 여러 지점 동시 표시", "focus_en",
                  "점 전체가 함께 한 번 맥동 후 정착 (순차 점등 금지)"),
    "count":     ("가리키기", "카운트 — 개수 총계", "focus_en + measure_en(개수, 없으면 marker 로 강등)",
                  "점 전체 맥동 1회, 총계 숫자는 절대 안 바뀜"),
    "manga":     ("가리키기", "만화 기호 — anime 톤 전용·자동", "지정 불가 — style=anime 면 항상 이것",
                  "집중선·충격 기호가 1~2초에 '탁' 붙고 정지"),
    "zone":      ("영역·구조", "영역 — 반투명 채움 + 경계 헤일로", "focus_en",
                  "경계선 따라 밝은 펄스 한 바퀴 후 정착"),
    "bracket":   ("영역·구조", "브래킷 — 모서리 4개로 영역", "focus_en",
                  "모서리가 살짝 조여들고 정착 (사각형으로 안 닫힘)"),
    "void":      ("영역·구조", "빈 공간을 부피로 채움", "focus_en",
                  "부피 고정(경계=설명 대상), 느린 숨쉬기만"),
    "reject":    ("영역·구조", "X — 아님·금지", "focus_en",
                  "X 고정, 획 위 빛 정착만"),
    "crack":     ("영역·구조", "균열선 + 새어나오는 헤일로", "focus_en",
                  "글로우가 균열 끝→끝 1회 주행, 균열은 절대 안 벌어짐"),
    "extent":    ("영역·구조", "뻗은 길이 전체 점등", "focus_en",
                  "길이 고정, 밝은 펄스가 끝→끝 1회 주행 후 정착"),
    "skeleton":  ("영역·구조", "골격 — 숨은 구조 네트워크", "focus_en",
                  "밝기 파도가 기점→말단으로 1회 퍼짐"),
    "measure":   ("계측·데이터", "치수선 — 어디서 어디까지", "focus_en (+measure_en, from_en/to_en 강력 권장)",
                  "선 안을 빛이 1회 주행, 눈금이 차례로 점등"),
    "gauge":     ("계측·데이터", "게이지 — 비율·차오름", "focus_en + measure_en 필수(없으면 미표시)",
                  "채움이 바닥→최종 눈높이로 1회 상승 후 고정"),
    "graph":     ("계측·데이터", "곡선 그래프 — 정량 관계", "focus_en (수치·라벨 불필요)",
                  "곡선 위를 빛 점이 최소→최대로 1회 주행"),
    "scale":     ("계측·데이터", "크기 비교 — 익숙한 것과", "focus_en + compare_en 필수",
                  "실루엣 완전 고정 — 걷기·회전·증식 금지 (2026-08-18 결정)"),
    "versus":    ("계측·데이터", "분할 비교 — 통념 vs 실제", "focus_en + compare_en 필수 · anno_label 금지",
                  "분할 레이아웃 고정, 패널 안 공기만 각자 살아있음"),
    "arrow":     ("움직임·힘", "화살표 — 방향 하나", "focus_en (+from_en/to_en)",
                  "길이 완전 고정, 꼬리→머리 하이라이트 1회"),
    "flow":      ("움직임·힘", "흐름 — 빛의 띠 (출발→작용점→도착)", "focus_en (+from_en/to_en, flow_of 로 내용색)",
                  "밝은 앞머리가 출발→작용점(강조)→도착 1회 주행"),
    "route":     ("움직임·힘", "동선 — 사람·물건이 지나간 길", "focus_en (+from_en/to_en)",
                  "바닥에 원근 고정, 빛 점이 시작→끝 마커로 1회 주행"),
    "trajectory":("움직임·힘", "탄도 — 발사점→착탄점 포물선", "focus_en(발사·착탄 지점 포함해 서술)",
                  "호 전체 고정, 빛 점이 발사→착탄 1회 주행"),
    "wave":      ("움직임·힘", "파동 — 퍼지는 동심원", "focus_en(파원 포함해 서술)",
                  "링 기하 고정, 밝기 펄스가 안→밖으로 1회"),
    "loadsplit": ("움직임·힘", "하중 분산 — 갈라지는 힘", "focus_en(갈라지는 지점 포함)",
                  "펄스가 진입→분기점에서 갈라져 양 갈래 동시 주행"),
    "tracer":    ("움직임·힘", "예광 — 날아가는 물체 자체가 발광", "focus_en(날아가는 것)",
                  "물체가 빛나며 경로를 1회 주행, 짧은 잔광 꼬리"),
    "intercept": ("움직임·힘", "요격 — 두 경로가 한 점에서 만남", "focus_en(만나는 지점 포함)",
                  "두 머리가 각 경로를 동시에 달려 만남점에서 함께 도착·1회 플레어"),
    "deflect":   ("움직임·힘", "튕겨나감 — 표면에서 방향이 꺾임", "focus_en(닿는 면 포함)",
                  "머리가 진입 다리를 달려 접점에서 플레어 후 꺾인 방향으로 나감"),
    "spin":      ("움직임·힘", "회전 — 나선 궤적 2~3바퀴", "focus_en(회전축 포함)",
                  "나선 고정, 빛 점이 회전 방향으로 1회 주행"),
}

kinds = sorted(M.ANNO_KINDS)
keys = set(M.VIDEO_ANNO_MODES)
today = datetime.date.today().isoformat()

def vid_mark(k):
    a = "O" if (k + "_animate") in keys or (k == "measure" and "animate" in keys) else "—"
    d = "O" if (k + "_draw") in keys or (k == "measure" and "draw" in keys) else "—"
    return a, d

def asm_mark(k):
    if k in M.ASSEMBLE_SKIP:
        return "제외"
    return "전용" if k in M.ASSEMBLE_STAGES else "기본"

L = []
L.append("# 강조 도구 총람 ⚙자동생성 — 고치지 말고 `python docs/_강조도구_뽑기.py` 로 다시 뽑을 것")
L.append("")
L.append(f"생성 {today} · 도구 {len(kinds)}종 (main.py `ANNO_KINDS` 실측) · 별칭 {dict(M.ANNO_ALIAS)}")
L.append("")
L.append("## 한 컷의 강조가 지나가는 길")
L.append("")
L.append("```")
L.append("컷 JSON(anno_kind·focus_en…)  →  이미지: ANNOTATION_* 문구로 2K에 굽는다")
L.append("                              →  영상:   VIDEO_ANNO_MODES[kind_animate] 가 '잠금+빛 1회'로 지킨다")
L.append("                              →  조립(옵션): CLEAN→INFO 사이를 ASSEMBLE_STAGES[kind] 순서로 조립")
L.append("```")
L.append("")
L.append("- **그래픽은 전부 2K 이미지에 굽는다. 영상은 절대 새로 그리지 않는다** (720p 재작도가 대표 실패).")
L.append("- 영상 판 공통 문법: 위치·크기·형태·길이 잠금 + 움직이는 것은 '그 안을 지나가는 빛 1회'뿐,")
L.append("  끝나면 정착(steady glow). 소실(fade out) 전면 금지.")
L.append("- `focus_en` 이 비면 강조는 통째로 안 들어간다 (이미지·영상 공통).")
L.append("")
L.append("## 도구별 총람")
L.append("")
L.append("| 도구 | 분류 | 무엇 | 필요한 필드 | 영상에서 | 영상판 A/D | 조립 |")
L.append("|---|---|---|---|---|---|---|")
for cat in ("가리키기", "영역·구조", "계측·데이터", "움직임·힘"):
    for k in kinds:
        c, desc, need, vid = INFO.get(k, ("?", "설명 없음 — INFO 표에 추가할 것", "?", "?"))
        if c != cat:
            continue
        a, d = vid_mark(k)
        L.append(f"| **{k}** | {cat} | {desc} | {need} | {vid} | {a}/{d} | {asm_mark(k)} |")
missing = [k for k in kinds if k not in INFO]
if missing:
    L.append("")
    L.append(f"⚠ INFO 표에 설명이 없는 도구: {missing} — 이 파일에 한 줄 추가할 것")
L.append("")
L.append("영상판 A/D = animate(구운 그래픽 유지+빛)/draw(영상이 직접 그림 — 잘 안 씀). `—` 는 판 없음.")
L.append("조립: 전용=ASSEMBLE_STAGES 에 조립 순서 있음 · 기본=공통 문구 · 제외=ASSEMBLE_SKIP")
L.append("(장면 자체를 바꾸는 도구라 조립 불가 → 구워서 유지로 폴백).")
L.append("")
L.append("## 색은 이렇게 정해진다")
L.append("")
L.append("1. flow 컷 + `flow_of` 지정 → 내용색 강제: " + ", ".join(f"{k}" for k in M.FLOW_COLORS))
L.append("2. 설정의 강조색이 특정 색이면 → 전부 그 색")
L.append("3. '자동'이면 → 톤별 표(`ANNO_COLOR_BY_STYLE`)")
L.append("")
L.append("## 글자 규칙 (화면에 실리는 텍스트)")
L.append("")
L.append("- `measure_en` 수치 12자 — 라틴/숫자만 남는다(한글 삭제: \"46년\"→\"46\" — 지침이 46Y 로 쓰게 함)")
L.append("- `anno_label` 영문 라벨 16자·2단어 — 강조색 박스 태그 + 리더선으로 굽는다. 편당 2~3컷만")
L.append("- 한글은 절대 굽지 않는다 (실측: \"등대 높이\"→\"롱대 늪이\"). 한글 설명은 편집 자막으로")
L.append("- **영상에는 수치·글자를 절대 새로 새기지 않는다** (실측: \"20km\"→\"2?:00\")")
L.append("")
L.append("## 조립 강조 (CLEAN→INFO)")
L.append("")
L.append("- 켜면 강조 컷마다 CLEAN(그래픽 없음)을 먼저 뽑고 INFO 를 편집 생성 — 비용 2배, CLEAN 은 `이미지/조립전/`")
L.append("- 영상은 CLEAN 에서 시작해 INFO 를 lastFrame 으로 고정 — 그래픽이 조립되며 끝상태 소실 불가")
L.append(f"- 조립 제외: {sorted(M.ASSEMBLE_SKIP)} — 장면 변경형이라 모델이 모핑으로 때움 (1편 실측)")
L.append("- Veo 는 first+last 보간이 **8초 전용** — 다른 초는 조립을 접고 경고만 낸다")
L.append("- arrow 조립은 '완성 화살표가 날아와 착지' — 몸통 성장 금지 (2026-08-18 결정)")
L.append("")
L.append("## 어디를 고치나")
L.append("")
L.append("| 고치고 싶은 것 | 위치 (main.py 상수) |")
L.append("|---|---|")
L.append("| 이미지에 그려지는 모양 | `ANNOTATION_<도구대문자>` 문구 |")
L.append("| 어떤 도구를 쓸지 판정·필수 필드 | `annotation_block()` 디스패치 |")
L.append("| 영상에서의 움직임 | `VIDEO_ANNO_MODES[\"<도구>_animate\"]` |")
L.append("| 조립 순서 | `ASSEMBLE_STAGES[\"<도구>\"]` / 제외는 `ASSEMBLE_SKIP` |")
L.append("| 도구 등록 자체 | `ANNO_KINDS` (+지침 enum — [📋 지침 복사] 로 claude.ai 교체 필요) |")
L.append("| 색 | `FLOW_COLORS` · `ANNO_COLOR_BY_STYLE` |")
L.append("")
L.append("도구를 새로 만들 때 채울 곳 6군데: 상수 → 디스패치 → `<도구>_animate` → 조립 스테이지 →")
L.append("`ANNO_KINDS` → 지침(enum+설명, 해시 갱신). 하나라도 빼먹으면 이 문서를 다시 뽑았을 때 표에 구멍이 보인다.")
L.append("")

out = os.path.join(ROOT, "docs", "06_강조도구.md")
io.open(out, "w", encoding="utf-8").write("\n".join(L))
print("생성:", out, f"({len(kinds)}종)")
