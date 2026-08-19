# 대본 스튜디오 — 프리셋별 주제 추천 / 대본 생성 (Claude API)
# UI 의존성 없음. main.py(PySide6)에서 import해서 쓰고, 단독 실행으로 테스트도 된다.
#   python studio.py presets
#   python studio.py topics "<프리셋 폴더명>"
#   python studio.py script "<프리셋 폴더명>" "<소재>"
#
# 프리셋 = 제작파일/ 아래 폴더 하나.
#   제작파일/<프리셋>/
#     *지침*.md        ← 필수. 이게 있어야 프리셋으로 인식된다
#     프리셋.json      ← 선택. 폼 항목·검수 규칙. 없으면 기본값
#     레퍼런스/        ← 선택. md/txt 전부 캐싱 프리픽스에 실린다
#     대본/            ← 자동 생성
#     제작이력.json    ← 자동 생성 (다음 추천의 중복 제외 근거)
#
# 지침+레퍼런스를 고정 프리픽스로 캐싱한다 → 두 번째 호출부터 입력비 1/10.

import json
import os
import re
import sys
from datetime import datetime

import anthropic

# ── 경로 ──────────────────────────────────────────────
# exe로 빌드하면 __file__은 임시폴더(_MEIPASS)를 가리킨다. 지침·대본은 사용자가 계속
# 고치는 파일이므로 exe 옆 폴더를 봐야 한다.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PRESET_ROOT = os.path.join(BASE_DIR, "제작파일")

# ── 모델 · 단가 ────────────────────────────────────────
# $/1M 토큰. 캐시 읽기 = 입력가 × 0.1, 캐시 쓰기 = 입력가 × 1.25
DEFAULT_MODEL = "claude-opus-5"
MODELS = [
    {"id": "claude-opus-5", "label": "Opus 5 (기본 · 추론 최강)", "in": 5.0, "out": 25.0},
    {"id": "claude-opus-4-8", "label": "Opus 4.8 (글맛 비교용 · 같은 값)", "in": 5.0, "out": 25.0},
    {"id": "claude-sonnet-5", "label": "Sonnet 5 (균형 · 60% 값)", "in": 3.0, "out": 15.0},
    {"id": "claude-haiku-4-5", "label": "Haiku 4.5 (대량 스캔용)", "in": 1.0, "out": 5.0},
]
PRICE = {m["id"]: m for m in MODELS}
USD_KRW = 1400  # 표시용 환산율

DEFAULT_CHECK = {
    "len": [500, 900], "len_target": "", "noun_ending": None, "noun_target": "",
    "questions": [1, 99], "max_sentence": 0, "banned_narration": [],
    "no_arabic_numerals": False, "no_same_ending_twice": False, "open_ending": False,
    # 첫 문장(훅) 검사 — 지침의 도입부 금지 4종을 실제로 잡는다
    "hook_ban": [], "hook_form": "", "hook_form_desc": "", "hook_hide_name": False,
}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── 프리셋 ────────────────────────────────────────────
def _preset_dir(pid):
    d = os.path.join(PRESET_ROOT, pid)
    if not os.path.isdir(d):
        raise RuntimeError(f"프리셋 폴더가 없습니다: {d}")
    return d


def _guide_path(d):
    cands = [f for f in os.listdir(d) if "지침" in f and f.lower().endswith(".md")]
    cands.sort()  # V1.0 < V1.1 … 파일명 정렬이 곧 버전 정렬
    return os.path.join(d, cands[-1]) if cands else None


def _preset_conf(d, pid):
    conf = {"label": pid, "tone": "", "unit": "편", "topic_intro": "", "score_max": 5,
            "fields": [], "script_checklist": [], "check": dict(DEFAULT_CHECK)}
    p = os.path.join(d, "프리셋.json")
    if os.path.exists(p):
        try:
            user = json.loads(_read(p))
            chk = dict(DEFAULT_CHECK); chk.update(user.pop("check", {}) or {})
            conf.update(user); conf["check"] = chk
        except Exception as e:
            conf["label"] = f"{pid} (프리셋.json 오류: {e})"
    return conf


def list_presets():
    """제작파일/ 아래에서 지침 md를 가진 폴더를 전부 프리셋으로 잡는다."""
    out = []
    if not os.path.isdir(PRESET_ROOT):
        return out
    for name in sorted(os.listdir(PRESET_ROOT)):
        d = os.path.join(PRESET_ROOT, name)
        if not os.path.isdir(d):
            continue
        g = _guide_path(d)
        if not g:
            continue
        conf = _preset_conf(d, name)
        out.append({"id": name, "label": conf["label"], "tone": conf["tone"],
                    "guide": os.path.basename(g), "fields": conf["fields"]})
    return out


def load_kit(pid):
    """지침 + 레퍼런스를 읽어 캐싱용 프리픽스로 만든다."""
    d = _preset_dir(pid)
    g = _guide_path(d)
    if not g:
        raise RuntimeError(f"'{pid}' 폴더에 지침 md가 없습니다 (파일명에 '지침' 포함 필요)")

    refs, names = [], []
    rd = os.path.join(d, "레퍼런스")
    if os.path.isdir(rd):
        for fn in sorted(os.listdir(rd)):
            # 밑줄로 시작하는 파일은 사람이 볼 메모·안내문이다 → 프롬프트에 싣지 않는다.
            # (안 거르면 "이 폴더 쓰는 법" 같은 글이 레퍼런스 대본인 줄 알고 학습된다)
            if fn.startswith("_"):
                continue
            if fn.lower().endswith((".md", ".txt")):
                refs.append(f"### 파일: {fn}\n\n{_read(os.path.join(rd, fn))}")
                names.append(fn)

    conf = _preset_conf(d, pid)
    return {"id": pid, "dir": d, "conf": conf, "guide": _read(g),
            "guide_file": os.path.basename(g), "refs": "\n\n---\n\n".join(refs),
            "ref_files": names, "chars": len(_read(g)) + sum(len(r) for r in refs)}


def _system_blocks(kit):
    """마지막 블록에 cache_control → 지침+레퍼런스 전체가 한 덩어리로 캐시된다.

    TTL을 1시간으로 잡는 이유: 기본값 5분은 '주제 추천 → 후보 읽어보고 → 대본 생성'
    사이에 만료돼 매번 캐시를 새로 쓴다(입력비 1.25배). 한 세션에 2회 이상 호출하는
    실제 사용 패턴에서는 1시간(쓰기 2배, 읽기 0.1배)이 더 싸다.
    """
    blocks = [{"type": "text", "text": "# 프로젝트 지침 (절대 규칙)\n\n" + kit["guide"]}]
    if kit["refs"]:
        blocks.append({"type": "text", "text": "# 레퍼런스 대본 (톤 학습용 · 문장 복제 금지)\n\n" + kit["refs"]})
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return blocks


# ── 제작 이력 (프리셋별) ────────────────────────────────
def _hist_path(pid):
    return os.path.join(_preset_dir(pid), "제작이력.json")


def history_load(pid):
    p = _hist_path(pid)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return []


def history_add(pid, entry):
    hist = history_load(pid)
    hist.append(entry)
    with open(_hist_path(pid), "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    return hist


def _history_note(pid, conf):
    """제작이력을 근거 문장으로 바꾼다. 중복 금지 + 로테이션 + 부정 소재 비율까지 계산해서 넘긴다."""
    hist = history_load(pid)
    if not hist:
        return "아직 제작한 편이 없습니다. 중복·로테이션 제약 없음."

    def line(h):
        tags = " ".join(str(v) for v in (h.get("fields") or {}).values() if v)
        return f"- {h.get('topic','?')} {tags} ({h.get('date','')})"

    out = ["이미 제작한 편 (같은 소재 금지):"] + [line(h) for h in hist[-25:]]

    rot = conf.get("rotation") or {}
    last = hist[-1].get("fields") or {}

    key = rot.get("avoid_repeat_field")
    if key and last.get(key):
        label = next((f["label"] for f in conf["fields"] if f["key"] == key), key)
        out.append(f"\n직전 편의 {label}: {last[key]} → 이번에는 다른 {label}로 갈 것.")

    # 부정 소재 비율 (지침 §2) — 최근 N편에서 몇 편이 부정 카테고리였는지 세어 넘긴다
    neg = rot.get("negative_values") or []
    if neg:
        win = int(rot.get("window") or 10)
        recent = hist[-win:]
        cnt = sum(1 for h in recent
                  if any(str(v) in neg for v in (h.get("fields") or {}).values()))
        ratio = rot.get("negative_max_ratio", 0.33)
        cap = int(len(recent) * ratio)
        out.append(f"\n부정 소재(기업 이슈·소비자 주의보) 최근 {len(recent)}편 중 {cnt}편 "
                   f"(상한 {int(ratio*100)}% = {cap}편).")
        if cnt >= cap:
            out.append("→ 상한에 도달했다. 이번 후보에는 부정 소재를 넣지 말고 "
                       "긍정·신기 소재로만 채울 것.")

    return "\n".join(out)


# ── 비용 ──────────────────────────────────────────────
def calc_cost(model, usage):
    p = PRICE.get(model, PRICE[DEFAULT_MODEL])
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    usd = (inp * p["in"] + cw * p["in"] * 1.25 + cr * p["in"] * 0.1 + out * p["out"]) / 1_000_000
    return {"input": inp, "output": out, "cache_write": cw, "cache_read": cr,
            "usd": round(usd, 5), "krw": int(round(usd * USD_KRW)), "cached": cr > 0}


def _client(api_key):
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("Anthropic API 키가 없습니다. 설정 탭에서 입력하세요.")
    return anthropic.Anthropic(api_key=key)


# ── 1) 주제 추천 ───────────────────────────────────────
def _topic_schema(fields):
    props = {
        "rank": {"type": "integer"},
        "topic": {"type": "string", "description": "소재 이름"},
        "hook": {"type": "string", "description": "한 줄 훅 (모순/의외의 각도)"},
        "score": {"type": "integer", "description": "판정 문항 통과 개수"},
        "reason": {"type": "string", "description": "추천 이유 한 줄"},
        "risk": {"type": "string", "description": "사실성 위험·중복 우려. 없으면 빈 문자열"},
    }
    for f in fields:
        props[f["key"]] = {"type": "string", "description": f.get("desc", f["label"])}
    req = list(props.keys())
    return {"type": "object",
            "properties": {"candidates": {"type": "array", "items": {
                "type": "object", "properties": props, "required": req,
                "additionalProperties": False}}},
            "required": ["candidates"], "additionalProperties": False}


def _ref_titles_block(raw):
    """관심 채널의 잘 나온 제목 — '무엇이 먹히는지' 감을 주는 용도.

    소재를 베끼라는 게 아니다. 오히려 지침의 중복·선점 금지 규칙이 여기에 그대로 걸린다.
    (§0-1 ④ 이미 우려먹은 소재 금지 · §0-b 선점 채널과 다른 각도 · §2 모방 한계선)
    """
    lines = [t.strip() for t in re.split(r"[\r\n]+", raw or "") if t.strip()]
    lines = [t for t in lines if not t.startswith(("※", "#", "//"))][:30]
    if not lines:
        return ""
    return (
        "\n\n[참고 — 이 소재·니치에서 실제로 나온 영상 제목들]\n"
        + "\n".join("- " + t for t in lines) +
        "\n괄호의 배수는 **그 채널 평균 조회수 대비 몇 배**인지다. 구독자 수가 아니라 "
        "그 채널의 평소 성적과 비교한 값이라, 배수가 높을수록 **채널 규모가 아니라 그 소재·각도 자체가 먹혔다**는 뜻이다.\n"
        "**이 목록의 첫 번째 쓰임새는 '이미 다뤄진 각도 목록'이다.**\n"
        "- 지침이 요구하는 *\"이 각도로 이미 나온 영상이 있는가\"* 자문을, 추측이 아니라 이 목록으로 판정하라.\n"
        "- **여기 있는 소재·각도는 이미 다뤄진 것이다.** 같은 것을 제안하지 마라 — 지침의 중복 금지에 걸린다.\n"
        "- 목록을 훑어 **아무도 안 건드린 빈자리**를 찾는 것이 이 작업의 핵심이다. "
        "빈자리를 찾았으면 reason에 *\"이 각도는 목록에 없다\"*를 한 줄로 밝혀라.\n"
        "- 배수가 높은 것들은 **왜 터졌는지(어떤 궁금증을 건드렸는지)**만 읽어내 그 원리를 다른 소재에 적용한다. "
        "소재 자체를 가져오지 않는다.\n"
        "- 같은 소재를 꼭 다뤄야겠다면 **명백히 다른 각도**여야 하고, 무엇이 다른지 reason에 밝혀라.\n"
        "- 제목 문구·표현을 그대로 또는 비슷하게 가져오지 마라 (모방 한계선).\n"
    )


def recommend_topics(api_key, pid, model=DEFAULT_MODEL, count=5, hint="", effort="high",
                     ref_titles=""):
    kit = load_kit(pid)
    conf = kit["conf"]
    client = _client(api_key)

    fdesc = "\n".join(
        f"- {f['key']}: {f['label']} — {f.get('desc','')} (가능한 값: {', '.join(f.get('options') or []) or '자유'})"
        for f in conf["fields"])
    prompt = (
        f"{conf['topic_intro'] or '지침의 주제 추천 규칙을 실행하세요.'}\n\n"
        f"후보 {count}개를 뽑습니다.\n\n{_history_note(pid, conf)}\n\n"
        f"각 후보에 아래 항목을 채우세요.\n{fdesc}\n\n"
        f"score는 판정 문항 통과 개수(만점 {conf['score_max']})입니다. 내림차순으로 rank를 1부터.\n"
        "risk에는 사실성 위험이나 이미 많이 다뤄진 소재인지에 대한 우려를 적고, 없으면 빈 문자열."
    )
    prompt += _ref_titles_block(ref_titles)
    if hint.strip():
        prompt += f"\n\n사용자 요청 방향: {hint.strip()}"

    resp = client.messages.create(
        model=model, max_tokens=16000, system=_system_blocks(kit),
        output_config={"format": {"type": "json_schema", "schema": _topic_schema(conf["fields"])},
                       "effort": effort},
        messages=[{"role": "user", "content": prompt}])

    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("응답을 JSON으로 읽지 못했습니다: " + text[:200])

    cands = sorted(data.get("candidates", []), key=lambda c: -c.get("score", 0))
    for i, c in enumerate(cands, 1):
        c["rank"] = i
    return {"ok": True, "candidates": cands, "score_max": conf["score_max"],
            "fields": conf["fields"], "cost": calc_cost(model, resp.usage), "kit": _kit_info(kit)}


# ── 2) 대본 생성 ───────────────────────────────────────
def write_script(api_key, pid, topic, fields=None, model=DEFAULT_MODEL, note="", effort="high"):
    kit = load_kit(pid)
    conf = kit["conf"]
    client = _client(api_key)
    fields = fields or {}

    # 미지정 항목을 '밝히고 시작'할지는 프리셋마다 다르다.
    #  · announce_choice=true  → 고른 항목을 먼저 한 줄로 밝히라고 요구
    #  · announce_choice=false → 사족 금지 프리셋이라 밝히면 지침 위반
    announce = conf.get("announce_choice", False)
    prompt = f"소재: {topic}\n"
    for f in conf["fields"]:
        v = (fields.get(f["key"]) or "").strip()
        if v:
            prompt += f"{f['label']}: {v}\n"
        elif announce:
            prompt += f"{f['label']}: 미지정 — 지침에 따라 가장 강한 것을 골라 먼저 한 줄로 밝히고 시작하세요.\n"
        else:
            prompt += f"{f['label']}: 미지정 — 지침에 따라 가장 강한 것을 스스로 고르되, 고른 이유를 따로 쓰지 말고 바로 출력 포맷으로 들어가세요.\n"
    if note.strip():
        prompt += f"추가 요청: {note.strip()}\n"

    prompt += "\n지침의 출력 포맷 그대로 출력하세요. 사족 금지.\n"
    if conf["script_checklist"]:
        prompt += "특히 확인할 것:\n" + "\n".join("- " + c for c in conf["script_checklist"])

    fact = conf.get("fact_check", True)
    if fact:
        prompt += (
            "\n\n[사실 확인 — 대본 쓰기 전에 먼저 한다. 예외 없다]\n"
            "대본에 들어갈 핵심 주장(연도·수치·인명·기업명·사건)은 **웹 검색으로 먼저 확인하고 쓴다.**\n"
            "\n"
            "**1. 검증 안 되는 주장은 아예 쓰지 않는다.**\n"
            "   검색으로 뒷받침되지 않으면 표현을 완화하는 게 아니라 **그 문장을 뺀다.**\n"
            "   훅이 그것 때문에 무너지면 대본 맨 위에 한 줄로 밝히고 대체 각도를 제안한다.\n"
            "**2. 모든 사실 주장에 출처를 단다.**\n"
            "   팩트 블록에 항목마다 `주장 — [등급] — 매체명 — https://전체URL` 형식으로 적는다.\n"
            "   URL은 검색 결과에 실제로 나온 것만 쓴다. **URL을 기억으로 재구성하지 않는다.**\n"
            "   숫자·인용문·날짜·인명은 출처에 적힌 표현을 그대로 옮긴다.\n"
            "**3. 출처끼리 충돌하면 충돌을 밝힌다.**\n"
            "   숨기고 하나만 쓰지 않는다. 팩트 블록에 양쪽을 적고 어느 쪽을 왜 골랐는지 한 줄로 쓴다.\n"
            "   신뢰도 순서: 1차 자료·학술 > 공공기관·기업 공식 > 주요 언론 > 위키 > 블로그·커뮤니티.\n"
            "   낭독 대본에는 고른 쪽만 싣되, 우세가 약하면 완화 표현(~라는 분석이 유력합니다)을 쓴다.\n"
            "**4. 지어내지 않는다.**\n"
            "   통계·인용문·날짜·인명·기관명을 추측으로 만들어내는 것은 금지다.\n"
            "   '대략 이쯤일 것'이라는 값을 구체적 숫자로 쓰지 않는다. 근거가 없으면 그 수치를 뺀다.\n"
            "\n"
            "확정이 안 되지만 소재상 꼭 필요한 것만 지침의 완화 표현(의혹/논란/~라는 주장/~라는 설)을 쓰고,\n"
            "그래도 불확실하면 해당 문장에 ⚠️ [검증 필요]를 붙인다.\n"
            "팩트 블록에는 검증한 항목마다 [정설]/[유력설]/[전설]/⚠️[검증 필요] 중 하나와 출처를 붙인다."
        )

    tools = [{"type": "web_search_20260209", "name": "web_search",
              "max_uses": int(conf.get("search_max_uses", 8))}] if fact else []

    msgs = [{"role": "user", "content": prompt}]
    usages, text = [], ""
    # 서버 툴(웹 검색)은 내부 반복 한도에 걸리면 stop_reason=pause_turn 으로 끊긴다.
    # 그때는 assistant 턴을 그대로 붙여 다시 보내면 서버가 이어서 진행한다.
    for _ in range(4):
        kw = {"model": model, "max_tokens": 16000, "system": _system_blocks(kit),
              "output_config": {"effort": effort}, "messages": msgs}
        if tools:
            kw["tools"] = tools
        resp = client.messages.create(**kw)
        usages.append(resp.usage)
        text += "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason == "refusal":
            raise RuntimeError("모델이 이 소재를 거절했습니다. 소재나 각도를 바꿔보세요.")
        if resp.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": resp.content}]

    searches = sum(getattr(u, "server_tool_use", None) and
                   getattr(u.server_tool_use, "web_search_requests", 0) or 0 for u in usages)
    cost = _merge_cost(model, usages)
    cost["searches"] = searches
    return {"ok": True, "text": text, "stats": analyze(extract_narration(text), pid),
            "cost": cost, "kit": _kit_info(kit), "fact_checked": bool(fact)}


def revise_script(api_key, pid, current, request, model=DEFAULT_MODEL, effort="high"):
    """이미 나온 대본에서 지적한 부분만 고친다.

    전체 재생성보다 빠르고 싸고, 무엇보다 마음에 들었던 문장이 안 날아간다.
    시스템 프리픽스(지침+레퍼런스)가 같아서 캐시가 그대로 적중한다.
    """
    kit = load_kit(pid)
    conf = kit["conf"]
    client = _client(api_key)
    if not (current or "").strip():
        raise RuntimeError("고칠 대본이 없습니다.")
    if not (request or "").strip():
        raise RuntimeError("무엇을 고칠지 적어주세요.")

    prompt = (
        "아래는 이미 완성된 대본입니다. **지적한 부분만 고치고 나머지는 그대로 두세요.**\n\n"
        "[고칠 점]\n" + request.strip() + "\n\n"
        "[현재 대본]\n" + current.strip() + "\n\n"
        "규칙:\n"
        "- 지적한 곳과 그것 때문에 어색해지는 최소 범위만 손댄다. 멀쩡한 문장은 한 글자도 바꾸지 않는다.\n"
        "- 지침의 출력 포맷 전체를 다시 출력한다 (제목 후보부터 끝까지). 바뀐 부분만 보내지 않는다.\n"
        "- 고치고 나서도 지침의 길이·어미·결말 규칙을 그대로 만족해야 한다.\n"
        "- 무엇을 왜 고쳤는지 설명하지 않는다. 대본만 출력한다.\n"
    )
    if conf.get("fact_check", True):
        prompt += ("- 사실을 바꾸라는 요청일 때만 웹 검색으로 확인한다. "
                   "문체·길이·훅만 고치는 요청이면 검색하지 않는다.\n")

    tools = ([{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]
             if conf.get("fact_check", True) else [])

    msgs = [{"role": "user", "content": prompt}]
    usages, text = [], ""
    for _ in range(4):
        kw = {"model": model, "max_tokens": 16000, "system": _system_blocks(kit),
              "output_config": {"effort": effort}, "messages": msgs}
        if tools:
            kw["tools"] = tools
        resp = client.messages.create(**kw)
        usages.append(resp.usage)
        text += "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason == "refusal":
            raise RuntimeError("모델이 이 수정 요청을 거절했습니다.")
        if resp.stop_reason != "pause_turn":
            break
        msgs = msgs + [{"role": "assistant", "content": resp.content}]

    return {"ok": True, "text": text, "stats": analyze(extract_narration(text), pid),
            "cost": _merge_cost(model, usages), "kit": _kit_info(kit)}


def _merge_cost(model, usages):
    """여러 번 왕복(pause_turn)했을 때 비용을 합산한다."""
    tot = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "usd": 0.0}
    for u in usages:
        c = calc_cost(model, u)
        for k in ("input", "output", "cache_write", "cache_read"):
            tot[k] += c[k]
        tot["usd"] += c["usd"]
    tot["usd"] = round(tot["usd"], 5)
    tot["krw"] = int(round(tot["usd"] * USD_KRW))
    tot["cached"] = tot["cache_read"] > 0
    return tot


def _kit_info(kit):
    return {"preset": kit["id"], "label": kit["conf"]["label"], "guide": kit["guide_file"],
            "refs": kit["ref_files"], "chars": kit["chars"], "tone": kit["conf"]["tone"]}


# ── 3) 자가 검수 — 프리셋 규칙과 대조 ────────────────────
_ENDINGS = ["습니다", "겁니다", "거예요", "인데요", "잖아요", "더라고요", "니까요", "거든요",
            "냐고요", "까요", "고요", "죠",
            # 반말 썰쇼츠 계열 (벤치마크 43편 실측에서 뽑은 어미군)
            "는 거", "다고", "라고", "는데", "던데", "겠는데", "인 듯", "정도",
            "함", "음", "임", "네", "지", "야", "고"]

# 지침이 금지하는 '닫힌 마무리' — 마침표 유무가 아니라 이걸로 판정한다.
# (자동 자막은 문장부호를 임의로 붙이므로 마침표는 신뢰할 수 없는 신호다)
_CLOSED_END = ["습니다", "합니다", "입니다", "됩니다", "좋아요", "구독", "알림 설정", "감사합니다"]

# 죽는 도입부 4종 (프리셋 지침의 도입부 규칙). 첫 문장에만 적용한다.
# 오탐이 나면 규칙이 무시당하므로, 확실히 잡히는 형태만 좁게 판정한다.
# '배경 설명형'은 안전한 정규식을 만들 수 없어 명시적 예고 표현만 잡는다 — 나머지는 프롬프트 몫.
_DEAD_HOOK = {
    "정의형": (r"^[^.?!]{2,20}(은|는)\s+[^.?!]{0,30}(인데요|인데[.!?…\s]*$|입니다|이라는|라는 뜻)",
             "첫 문장이 이미 답이라 구멍이 안 생깁니다"),
    "공감형": (r"(다들|여러분|우리)[^.?!]{0,20}(시죠|하시죠|죠\?|잖아요|지\?)",
             "아는 사실을 확인만 시켜서 정보 획득이 0입니다"),
    "배경설명": (r"(알아볼|살펴볼|알려드릴|파헤쳐\s?볼|이야기해\s?볼)[^.?!]{0,8}(건데요|겁니다|게요|까요)",
              "서론이 있다는 건 본론이 멀다는 신호입니다"),
    "연대기": (r"^\s*(서기\s*|기원전\s*)?[\d일이삼사오육칠팔구천백십영공]{2,}\s*년[\s,]",
             "사건 대신 날짜를 먼저 줬습니다"),
}


def extract_narration(md):
    """출력 마크다운에서 🎙️ 낭독용 스크립트 블록만 뽑는다."""
    m = re.search(r"낭독용 스크립트.*?\n(.*?)(?=\n---|\n###|\Z)", md, re.S)
    body = m.group(1) if m else md
    body = re.sub(r"^\s*\(.*?\)\s*$", "", body, flags=re.M)  # 포맷 설명 괄호줄 제거
    return body.strip()


def analyze(text, pid=None):
    """지침 목표치와 실제를 비교. 대본을 붙여넣기만 해도 쓸 수 있고 API 호출은 없다."""
    if not text.strip():
        return {}
    chk = dict(DEFAULT_CHECK)
    if pid:
        try:
            chk.update(_preset_conf(_preset_dir(pid), pid)["check"])
        except Exception:
            pass

    sents = [s.strip() for s in re.split(r"(?<=[.?!])\s+|\n+", text) if s.strip()]
    if not sents:
        return {}
    lens = [len(s) for s in sents]

    endings, seq = {}, []
    for s in sents:
        body = s.rstrip(".?!…~ ")
        for e in sorted(_ENDINGS, key=len, reverse=True):
            if body.endswith(e):
                endings[e] = endings.get(e, 0) + 1
                seq.append(e)
                break
        else:
            endings["체언"] = endings.get("체언", 0) + 1
            seq.append("체언")

    n = len(sents)
    q = sum(1 for s in sents if s.endswith("?"))
    pct = {k: round(v * 100 / n, 1) for k, v in sorted(endings.items(), key=lambda kv: -kv[1])}
    chars = len(text)
    warn = []

    lo, hi = chk["len"]
    if not lo <= chars <= hi:
        warn.append(f"길이 {chars}자 — 목표 {chk['len_target'] or f'{lo}~{hi}자'}에서 벗어남")

    if chk["noun_ending"]:
        nlo, nhi = chk["noun_ending"]
        che = pct.get("체언", 0)
        if che < nlo:
            warn.append(f"체언 마침 {che}% — 목표 {chk['noun_target']}. 명사로 끊는 문장이 거의 없어 리듬이 밋밋합니다")
        elif che > nhi:
            warn.append(f"체언 마침 {che}% — 목표 {chk['noun_target']}. 문장이 툭툭 끊깁니다")

    qlo, qhi = chk["questions"]
    if q < qlo:
        warn.append(f"의문형 {q}회 — 최소 {qlo}회 (중간 의문형을 넣으세요)")
    elif q > qhi:
        warn.append(f"의문형 {q}회 — 최대 {qhi}회 초과")

    if chk["max_sentence"] and max(lens) > chk["max_sentence"]:
        warn.append(f"최장 문장 {max(lens)}자 — {chk['max_sentence']}자 초과")

    hits = [w for w in chk["banned_narration"] if w in text]
    if hits:
        warn.append(f"낭독 라인 금지 표현: {', '.join(hits)} — TTS 오독/종료 신호")

    if chk["no_arabic_numerals"]:
        nums = sorted(set(re.findall(r"\d[\d,]*", text)))
        if nums:
            warn.append(f"아라비아 숫자 {', '.join(nums[:5])} — 한글로 읽는 대로 쓰세요")

    if chk["no_same_ending_twice"]:
        dup = [seq[i] for i in range(1, len(seq)) if seq[i] == seq[i - 1] and seq[i] != "체언"]
        if dup:
            uniq = sorted(set(dup))
            warn.append(f"같은 어미 연속: {', '.join(uniq)} ({len(dup)}곳) — 하나를 다른 어미로 교체")

    # ── 첫 문장(훅) 검사 ──
    hook = sents[0]
    hbody = hook.rstrip(".?!…~ ")
    for key in chk.get("hook_ban") or []:
        pair = _DEAD_HOOK.get(key)
        if pair and re.search(pair[0], hook):
            warn.append(f"첫 문장이 {key} 도입부 — {pair[1]}")

    hf = chk.get("hook_form")
    if hf and not re.search(hf, hook):
        warn.append(f"첫 문장이 {chk.get('hook_form_desc') or hf} 형식이 아닙니다 — 훅 문법 위반")

    # '첫 문장 명사 마침' 검사는 넣지 않는다.
    #  ① 근거였던 18/18은 자동 자막(ASR) 추출본이고, 손으로 쓴 기준대본(세진) 2편 중 1편은
    #     서술어로 끝난다 — 규칙이 아니라 경향이다.
    #  ② _ENDINGS의 짧은 어미(음·임·함·지)가 '얼음·마음' 같은 명사를 오탐한다.
    #  경향은 지침(§0-훅)에만 남기고 자동 경고는 걸지 않는다.

    # 소재 이름이 훅에 새는지: 2번째 문장의 정체 구절 끝 낱말이 훅에도 있으면 이미 밝힌 것.
    # 3자 미만은 일반 명사(벽·다리·집)라 훅에 있는 게 정상이므로 제외한다.
    if chk.get("hook_hide_name") and len(sents) >= 2:
        s2 = sents[1].rstrip(".?!…~ ")
        for e in sorted(_ENDINGS, key=len, reverse=True):
            if s2.endswith(e):
                s2 = s2[: -len(e)]
                break
        tok = s2.split()[-1] if s2.split() else ""
        tok = re.sub(r"(이|가|은|는|을|를|의)$", "", tok)
        if len(tok) >= 3 and tok in hook:
            warn.append(f"훅에 소재 이름('{tok}')이 이미 나왔습니다 — 정체는 2번째 문장에서 공개하세요")

    if chk["open_ending"]:
        tail = sents[-1].rstrip(".?!… ")
        hit = [w for w in _CLOSED_END if tail.endswith(w) or w in sents[-1]]
        if hit:
            warn.append(f"마지막 문장이 닫힌 마무리({', '.join(hit)}) — 비대칭 루프 결말(반말로 툭 끊기) 위반")

    return {"chars": chars, "sentences": n, "avg_len": round(sum(lens) / n, 1),
            "max_len": max(lens), "questions": q, "endings": pct, "warnings": warn}


# ── 4) 저장 ────────────────────────────────────────────
def save_script(pid, topic, text, fields=None):
    d = _preset_dir(pid)
    out = os.path.join(d, "대본")
    os.makedirs(out, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "", topic)[:40] or "무제"
    path = os.path.join(out, f"{datetime.now():%Y%m%d_%H%M}_{safe}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    history_add(pid, {"topic": topic, "fields": fields or {},
                      "date": f"{datetime.now():%Y-%m-%d}", "file": os.path.basename(path)})
    return path


def out_dir(pid):
    d = os.path.join(_preset_dir(pid), "대본")
    os.makedirs(d, exist_ok=True)
    return d


# ── 단독 실행 테스트 ────────────────────────────────────
if __name__ == "__main__":
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        cp = os.path.join(BASE_DIR, "config.json")
        if os.path.exists(cp):
            key = json.load(open(cp, encoding="utf-8")).get("anthropic_key", "")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "presets"
    pid = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "presets":
        for p in list_presets():
            k = load_kit(p["id"])
            print(f'· {p["id"]}  →  {p["label"]}')
            print(f'    지침 {k["guide_file"]} · 레퍼런스 {len(k["ref_files"])}개 · 프리픽스 {k["chars"]:,}자')
            print(f'    폼 {[f["label"] for f in p["fields"]]}')
    elif cmd == "topics":
        r = recommend_topics(key, pid)
        for c in r["candidates"]:
            print(f'{"★" if c["rank"] == 1 else " "}{c["rank"]}. {c["topic"]} — {c["score"]}/{r["score_max"]}')
            print(f'   훅: {c["hook"]}')
            if c.get("risk"):
                print(f'   ⚠ {c["risk"]}')
        print("\n비용:", r["cost"])
    elif cmd == "script":
        r = write_script(key, pid, sys.argv[3] if len(sys.argv) > 3 else "테스트 소재")
        print(r["text"])
        print("\n검수:", json.dumps(r["stats"], ensure_ascii=False, indent=2))
    else:
        print("사용법: python studio.py [presets | topics <프리셋> | script <프리셋> <소재>]")
