"""타임코드 없는 대본을 자막 분할 탭에 넣었을 때 (2026-08-06 실사용 케이스)."""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 콘솔이 cp949 여도 ✅/❌ 가 안 깨지게
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

SCRIPT = """세진
백 년간 안 바뀐 모기향의 비밀
여름마다 피 우는 그 모기향, 왜 하필 소용돌이 모양일까?
사실 저 모양은 예뻐서 만든 게 아니라, 백 년 전 한 남자가 몇 년을 갈아 넣고 겨우 찾아낸 답이라는데.
천팔백구십년대 일본에서, 국화의 일종인 제충국 가루에 벌레를 죽이는 성분이 있다는 걸 알게 된 남자는 이걸 태운 연기로 모기를 잡아 보기로 했다고.
그렇게 나온 첫 제품이 절에서 피우는 향처럼 생긴 막대 모기향.
근데 여기서 대형 사고가 터지는데, 이게 사십 분이면 다 타서 사라져 버린 거.
사람이 잠들 때쯤 향은 이미 꺼져 있고, 모기는 그때부터 신나게 물어뜯기 시작한 거지.
그럼 그냥 길게 만들면 되는 거 아니냐고?
길게 뽑으면 금방부러지고, 굵게 만들면 연기가 매캐해서 사람이 먼저 못 버텼다고.
그 상태로 몇 년을 막혀 있던 남자에게 답을 준 사람은 따로 있었는데, 그건 바로 남자의 아내였다는 거.
뱀처럼 둘둘 말아 보라는 한마디에 같은 재료를 감아 버리니, 부러지지도 않으면서 길이만 늘어나 일곱 시간을 버티게 됐고.
자는 내내 안 꺼지는 모기향은 그렇게 세상에 나왔다고.
백 년 넘게 모양이 한 번도 안 바뀌었는데, 아직도 이걸 이기는 모양이 안 나왔다는 게"""

SRT = """1
00:00:00,000 --> 00:00:04,200
여름마다 피우는 그 모기향, 왜 하필 소용돌이 모양인지 생각해 본 적 있냐?
"""

api = M.Api()
BAD = 0
r = api.sub_split({"srt": SCRIPT, "max_chars": 14, "min_dur": 0.7})

checks = [
    ("대본을 거절하지 않는다", r.get("ok") is True),
    ("추정 플래그가 켜진다", r.get("estimated") is True),
    # 2026-08-19 사양 변경: 자동 제거 폐지 — 붙여넣은 줄을 전부 읽는다.
    # (훅 첫 줄이 화자·제목과 같은 모양이라 대본 첫 문장이 통째로 안 읽히는 사고가 났다.
    #  자동 판별로는 못 가르므로 사용자가 안 읽을 줄을 지우고 넣기로 결정)
    ("아무 줄도 버리지 않는다", r.get("dropped") == []),
    ("붙여넣은 줄 수 그대로 (14줄)", r.get("before") == 14),
    ("화면폭에 맞게 더 쪼갠다", r.get("after") > r.get("before")),
    ("총 길이가 그럴듯하다 (60~150초)", 60 <= r.get("total", 0) <= 150),
    ("SRT 타임코드를 만든다", "-->" in r.get("srt", "")),
    ("빠진 본문이 없다",
     "아직도 이걸 이기는" in " ".join(c["text"] for c in r["cues"])),
]
for name, cond in checks:
    BAD += (not cond)
    print(f" {'OK ' if cond else '❌ '} {name}")

print(f"\n {r['before']}문장 → {r['after']}줄 · 총 {r['total']}초 · 제외 {r.get('dropped')}")
for c in r["cues"][:8]:
    print(f"   {c['i']:2d} {c['start']:6.2f} +{c['dur']:4.2f}s [{c['len']:2d}자] {c['text']}")

# SRT 를 넣으면 추정 모드로 새지 않아야 한다
r2 = api.sub_split({"srt": SRT, "max_chars": 14})
ok = r2.get("ok") and not r2.get("estimated")
BAD += (not ok)
print(f"\n {'OK ' if ok else '❌ '} SRT 는 그대로 타임코드 사용 (estimated={r2.get('estimated')})")

# 빈 입력은 여전히 거절
r3 = api.sub_split({"srt": "   "})
ok = r3.get("ok") is False
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 빈 입력은 거절")

# 음성 총 길이를 주면 거기에 맞춰 비례 배분된다 (타입캐스트 속도 설정과 무관)
for total in (62.0, 105.5):
    rt = api.sub_split({"srt": SCRIPT, "max_chars": 14, "min_dur": 0.7, "total": total})
    got = rt["cues"][-1]["start"] + rt["cues"][-1]["dur"]
    ok = rt.get("fitted") and abs(got - total) < 0.6 and rt["cues"][0]["start"] == 0
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} 총 {total}초로 맞추기 → 끝 {got:.1f}초 (fitted={rt.get('fitted')})")

# 총 길이를 안 주면 fitted 는 꺼진 채 추정 그대로
ok = api.sub_split({"srt": SCRIPT})["fitted"] is False
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 총 길이 없으면 fitted=False")

# ── 자막 줄 나누기 (2026-08-11 제보) ────────────────────────────
# ① 종결부호 뒤는 길이와 무관하게 끊는다 — 짧으면 다음 문장을 끌어와 한 줄에 두 문장이
#    섞였다 ("실어버린 거. 비결은 성분이"). 예전엔 max_chars 의 절반을 넘어야만 끊었다.
# ② 줄 길이를 고르게 — 탐욕으로 채우면 줄 끝에 수식어가 홀로 남는다
#    ("찾다가 만들어낸 군용 / 포장이었고" → '군용 포장'이 갈라진다).
T = ("찾다가 만들어낸 군용 포장이었고 이걸 본 나사가 그대로 우주선에 실어버린 거. "
     "비결은 성분이 아니라 순서인데 음식을 봉지에 넣는 순서가 핵심이었죠.")
for mc in (14, 16, 18, 20):
    parts = M.sub_chunks(T, mc)
    ok = "".join(parts).replace(" ", "") == T.replace(" ", "")
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} max_chars={mc} 글자 유실 없음")
    mixed = next((x for x in parts if any(c in x[:-1] for c in ".?!…")), None)
    BAD += (mixed is not None)
    print(f" {'OK ' if not mixed else '❌ '} max_chars={mc} 한 줄에 두 문장이 안 섞임"
          + (f" — 섞인 줄: {mixed}" if mixed else ""))
    over = [x for x in parts if len(x) > mc and " " in x]
    BAD += bool(over)
    print(f" {'OK ' if not over else '❌ '} max_chars={mc} 폭 초과 없음"
          + (f" — {over}" if over else ""))

p18 = M.sub_chunks("찾다가 만들어낸 군용 포장이었고 이걸 본 나사가", 18)
ok = not any(x.endswith(("군용", "이걸", "본")) for x in p18)
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 균형 분할 — 수식어가 줄 끝에 홀로 안 남음 {p18}")

# 의미 덩어리 보호 — 부정어·수사는 뒷말과, 의존명사·단위는 앞말과 붙어야 한다.
# "안 / 들어가" 는 읽는 순간 뜻이 뒤집히고, "한 / 방울도" 는 수량이 안 읽힌다 (2026-08-11 제보)
# 의존명사 판별은 **어절 전체**로 해야 한다. startswith 로 하면 "원래"(원)·"만든"(만)·
# "데이터"(데)·"지금"(지)·"바로"(바)·"터널"(터)까지 앞말에 붙어 덩어리가 뭉개진다
# (2026-08-11 실측: "그 봉지가 원래" / "나가려고 만든" 이 한 덩어리가 됐다)
for w, want in [("게", True), ("거.", True), ("것?", True), ("년을", True), ("개가", True),
                ("방울도", True), ("거였는데?", True), ("것이다", True),
                ("원래", False), ("만든", False), ("데이터", False), ("지금", False),
                ("바로", False), ("터널", False), ("적당히", False), ("채우고", False)]:
    got = M.is_sub_glue(w)
    BAD += (got != want)
    print(f" {'OK ' if got == want else '❌ '} 앞말에 붙임 {w!r} = {got} (기대 {want})")

# 제보 케이스 — 의존명사가 어미와 붙어 길어진 형태가 줄 첫머리로 밀려나면 안 된다
p10 = M.sub_chunks("그 봉지가 원래 우주 나가려고 만든 거였는데?", 10)
ok = "만든 거였는데?" in p10
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} '만든 거였는데?' 가 한 줄 {p10}")

T2 = "상온에 일 년을 굴려도 멀쩡한 은박 봉지가 있는데 방부제가 한 방울도 안 들어가 있다는 거."
for mc in (8, 10, 12, 14, 16):
    parts = M.sub_chunks(T2, mc)
    split = [x for x in parts if x.endswith((" 한", " 안", " 두", " 세", " 못"))]
    BAD += bool(split)
    print(f" {'OK ' if not split else '❌ '} max_chars={mc} 부정어·수사가 줄 끝에 안 남음"
          + (f" — {split}" if split else ""))
    joined = " / ".join(parts)
    keep = all(k in joined for k in ("한 방울도", "안 들어가"))
    BAD += (not keep)
    print(f" {'OK ' if keep else '❌ '} max_chars={mc} '한 방울도'·'안 들어가' 묶음 유지"
          + ("" if keep else f" — {joined}"))


# ── 끊어 읽는 자리 (2026-08-11 사용자 예시로 확정) ──────────────────
# ① 연결어미 뒤에서는 길이와 무관하게 끊는다  ② 조사 없이 끝난 수식어는 뒷말과 붙는다
print("\n[끊어 읽는 자리]")
for text, must in (
        # '-어도/-아도' 양보어미 — 목록에 없어서 "굴려도 멀쩡한 은박" 으로 이어졌다
        ("상온에 일 년을 굴려도 멀쩡한 은박 봉지가 있는데", ["굴려도", "멀쩡한 은박 봉지가"]),
        # 조사 없이 끝난 어절 = 뒷말을 꾸미는 말. 가르면 홀로 떨어진다
        ("미군 연구소가 깡통 대신 짊어질 밥을 찾다가 만들어낸 군용 포장이었고", ["군용 포장이었고"]),
        ("근데 이 군용 포장을 한국 밥상에 처음 끌고 내려온 제품이 하필 카레였다는 거",
         ["이 군용 포장을", "처음 끌고", "하필 카레였다는 거"]),
        # 의존명사 '다음' 은 앞말에 붙는다 ("밀봉한 / 다음 그 상태로" 방지)
        ("음식을 봉지에 먼저 넣고 완전히 밀봉한 다음 그 상태로", ["밀봉한 다음"]),
        # 관형절은 꾸밈받는 명사와 한 줄에
        ("썩을 방법 자체가 사라지는 거", ["사라지는 거"]),
        ("새로 들어올 구멍도 없으니", ["들어올 구멍도"]),
):
    parts = M.sub_chunks(text, 10)
    joined = " / ".join(parts)
    for m in must:
        ok = any(m in c for c in parts)     # 한 조각 안에 통째로 들어 있으면 된다
        BAD += (not ok)
        print(f" {'OK ' if ok else '❌ '} {m!r} 가 한 줄" + ("" if ok else f" — {joined}"))

# 말 텀(쉼)이 있으면 그 자리를 우선한다 — 문법 규칙이 못 잡는 경계도 여기서 드러난다
ws = "그럼 대체 뭘 넣은 거냐면 아무것도 안 넣은 게 정답이라고".split()
gaps = [0.0] * len(ws)
gaps[ws.index("거냐면")] = 0.35          # 여기서 실제로 쉬었다면
got = M.sub_chunks(" ".join(ws), 10, gaps)
ok = any(c.endswith("거냐면") for c in got)
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 쉼이 있는 자리에서 끊음 — {' / '.join(got)}")

# 어절 수가 안 맞는 gaps 는 무시하고 문법 규칙만 쓴다 (엉뚱한 자리에서 끊기지 않게)
BAD += (M.sub_chunks("안에 있던 균은 다 죽고", 10, [0.5]) != M.sub_chunks("안에 있던 균은 다 죽고", 10))
print(" OK  길이가 안 맞는 쉼 정보는 무시")

print(f"\n{'❌ ' + str(BAD) + '건 실패' if BAD else '✅ 전 항목 통과'}")
