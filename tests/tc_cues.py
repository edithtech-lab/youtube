"""단어별 실측 타임스탬프 → 자막 줄 묶기 (타입캐스트 with-timestamps 응답 형태)."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 콘솔이 cp949 여도 ✅/❌ 가 안 깨지게
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

BAD = 0
# 실제 응답 형태: {"text": "단어", "start": 초, "end": 초}
SENT = "여름마다 피우는 그 모기향, 왜 하필 소용돌이 모양인지 생각해 본 적 있냐?"
words, t = [], 0.0
for w in SENT.split():
    d = 0.11 * len(w) + 0.12
    words.append({"text": w, "start": round(t, 2), "end": round(t + d, 2)})
    t += d + 0.04

cues = M.words_to_cues(words, max_chars=14, min_dur=0.7)
print(f" 단어 {len(words)}개 → 자막 {len(cues)}줄 (총 {words[-1]['end']:.2f}초)")
for c in cues:
    print(f"   {c['start']:5.2f} → {c['end']:5.2f}  [{len(c['text']):2d}자] {c['text']}")

joined = " ".join(c["text"] for c in cues)
checks = [
    ("글자가 빠지지 않는다", joined.replace(" ", "") == SENT.replace(" ", "")),
    ("각 줄이 최대 글자수 이내", all(len(c["text"]) <= 14 for c in cues)),
    ("첫 줄이 첫 단어 시각에서 시작", cues[0]["start"] == words[0]["start"]),
    ("마지막 줄이 마지막 단어 시각에서 끝", abs(cues[-1]["end"] - words[-1]["end"]) < 0.75),
    ("시간이 겹치지 않는다",
     all(cues[i]["end"] <= cues[i + 1]["start"] + 0.001 for i in range(len(cues) - 1))),
    ("시간이 뒤로만 흐른다", all(c["end"] > c["start"] for c in cues)),
]
for name, cond in checks:
    BAD += (not cond)
    print(f" {'OK ' if cond else '❌ '} {name}")

# 짧게 스치는 줄은 다음 줄을 침범하지 않는 선에서만 늘린다
tiny = [{"text": "응", "start": 0.0, "end": 0.12},
        {"text": "그래서", "start": 0.30, "end": 0.90}]
c2 = M.words_to_cues(tiny, max_chars=4, min_dur=0.7)
ok = len(c2) == 2 and c2[0]["end"] <= c2[1]["start"] + 0.001
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 최소 노출 보정이 다음 줄을 안 밀침 ({c2[0]['end']} ≤ {c2[1]['start']})")

# 의존명사가 줄 첫머리에 오지 않는다
gl = []
t = 0.0
for w in "저 모양은 예뻐서 만든 게 아니라 백 년 전".split():
    gl.append({"text": w, "start": round(t, 2), "end": round(t + 0.3, 2)}); t += 0.34
c3 = M.words_to_cues(gl, max_chars=8, min_dur=0.5)
ok = not any(c["text"].startswith(("게 ", "것 ", "수 ", "때 ")) or c["text"] in ("게", "것", "수", "때")
             for c in c3)
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 의존명사가 줄 첫머리에 안 옴 → {[c['text'] for c in c3]}")

# ── 낭독의 쉼으로 문장 경계 찾기 (2026-08-11 제보) ──────────────
# 음슴체 대본("~거", "~고", "~림")은 마침표가 없어 부호로는 문장 끝을 못 찾는다.
# 대신 사람은 문장 끝에서 숨을 쉰다 — 실측: 같은 문장 안 0.04초 / 문장 경계 0.2~0.8초.
def _w(rows):
    return [{"text": t, "start": a, "end": b} for t, a, b in rows]


W = [("우주선에", 0.0, 0.5), ("실어버린", 0.5, 0.9), ("거", 0.9, 1.2),
     ("비결은", 1.6, 2.0), ("성분이", 2.0, 2.4)]          # "거" 뒤에 0.4초 쉼
cues = M.words_to_cues(_w(W), 12)
mixed = [c["text"] for c in cues if "거" in c["text"] and "비결은" in c["text"]]
BAD += bool(mixed)
print(f" {'OK ' if not mixed else '❌ '} 0.4초 쉼에서 문장이 갈린다 "
      + (f"— 섞인 줄: {mixed}" if mixed else f"{[c['text'] for c in cues]}"))

# 쉼이 없으면(0.04초) 붙어 있어야 한다 — 아무 데서나 끊으면 안 된다
W2 = [("음식을", 0.0, 0.4), ("봉지에", 0.44, 0.8), ("먼저", 0.84, 1.1)]
c2 = M.words_to_cues(_w(W2), 12)
BAD += (len(c2) != 1)
print(f" {'OK ' if len(c2) == 1 else '❌ '} 짧은 간격은 안 끊는다 {[c['text'] for c in c2]}")

# 부정어·수사는 뒷말과 함께 — "안 / 들어가" 는 읽는 순간 뜻이 뒤집힌다
W3 = [("방부제가", 0.0, 0.5), ("한", 0.5, 0.7), ("방울도", 0.7, 1.1),
      ("안", 1.1, 1.3), ("들어가", 1.3, 1.7)]
c4 = M.words_to_cues(_w(W3), 10)
tail = [c["text"] for c in c4 if c["text"].endswith((" 한", " 안"))]
BAD += bool(tail)
print(f" {'OK ' if not tail else '❌ '} 부정어·수사가 줄 끝에 안 남음 {[c['text'] for c in c4]}")

# 글자 유실 없음 — 뒷말과 붙이려고 붙잡아 둔 어절을 흘리기 쉽다 (문장이 그 어절로 끝날 때)
for i, W4 in enumerate((W, W2, W3, W3 + [("있다는", 1.7, 2.0), ("거", 2.0, 2.2)],
                        [("모래를", 0.0, 0.4), ("한", 0.4, 0.6)])):
    src = "".join(t for t, _, _ in W4)
    got = "".join(c["text"] for c in M.words_to_cues(_w(W4), 10)).replace(" ", "")
    BAD += (got != src)
    print(f" {'OK ' if got == src else '❌ '} 글자 유실 없음 #{i + 1}"
          + ("" if got == src else f" — {got!r} ≠ {src!r}"))

# ── 대본 줄바꿈을 자막 경계로 (2026-08-11) ──────────────────────
# 사용자는 대본을 문장별로 줄 나눠서 넣는다. 그게 사람이 직접 그은 경계라 부호·호흡
# 추측보다 정확한데, 예전엔 tc_speak 가 lines 를 갖고도 words_to_cues 에 안 넘겨 버렸다
# → "정답이라고 사실 이 / 봉지는" 처럼 두 줄이 한 자막에 섞였다.
LN = ["그럼 대체 뭘 넣은 거냐면 아무것도 안 넣은 게 정답이라고",
      "사실 이 봉지는 슈퍼에 팔려고 만든 물건이 아니었는데"]
ws, t = [], 0.0
for ln in LN:                      # 줄 사이에 쉼을 두지 않는다 — 경계 감지만으로 끊겨야 한다
    for w in ln.split():
        d = len(w) * 0.13
        ws.append({"text": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d + 0.03
got = [c["text"] for c in M.words_to_cues(ws, 10, lines=LN)]
mixed = [x for x in got if "정답이라고" in x and "사실" in x]
BAD += bool(mixed)
print(f" {'OK ' if not mixed else '❌ '} 대본 줄이 다른 자막과 안 섞임"
      + (f" — {mixed}" if mixed else f" {got[:5]}…"))
# 줄 안에서는 폭에 맞춰 계속 쪼개야 한다 (경계만 지키고 손 놓으면 한 줄이 30자가 된다)
over = [x for x in got if len(x) > 10 and " " in x]
BAD += bool(over)
print(f" {'OK ' if not over else '❌ '} 줄 안에서도 폭 기준으로 쪼갬" + (f" — {over}" if over else ""))
# 줄을 안 주면 예전처럼 부호·호흡으로만 판단한다 (하위 호환)
BAD += (not M.words_to_cues(ws, 10))
print(f" {'OK ' if M.words_to_cues(ws, 10) else '❌ '} lines 를 안 줘도 동작 (하위 호환)")
src = "".join(w["text"] for w in ws)
BAD += ("".join(got).replace(" ", "") != src)
print(f" {'OK ' if ''.join(got).replace(' ', '') == src else '❌ '} 줄 경계에서 글자 유실 없음")

print(f"\n{'❌ ' + str(BAD) + '건 실패' if BAD else '✅ 전 항목 통과'}")
