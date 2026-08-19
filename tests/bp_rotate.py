"""BytePlus 계정 배분 — 영상은 '오늘', 이미지는 '누적'.

영상 토큰은 **매일 보상으로 채워진다**(전날 사용량만큼, 일 상한까지). 그래서 어느 계정을
쓸지는 오늘 얼마 썼나로 정해야 한다. 누적으로 정렬하면 두 가지가 동시에 망가진다:
 ① 누적이 적은 계정 하나만 계속 쓰인다 — 오늘 이미 썼어도 여전히 1순위라서
 ② 누적이 상한을 넘긴 계정은 오늘 한 토큰도 안 썼는데 영구 제외된다
실측 2026-08-13: 5계정 중 1개만 쓰이고 1개는 영구 제외 — 하루 한도 2,500만 중 500만만 받았다.

이미지(Seedream)는 반대다. '무료 몇 장'은 총량이라 누적이 맞다. 두 통을 섞으면 안 된다.
"""
import sys, os
from datetime import datetime, timedelta
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


TODAY = datetime.now().strftime("%Y-%m-%d")
YDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
ACC = "\n".join(f"ark-0000-0000-0000-0000-00000000{i:02d}aaaa | 계정{i}" for i in (1, 2, 3))
KID = {i: f"00000000{i:02d}aaaa"[-10:] for i in (1, 2, 3)}

CFG = {"byteplus_accounts": ACC, "byteplus_prefer": "free", "byteplus_rotate": "spread",
       "byteplus_on_empty": "paid", "byteplus_key": "", "byteplus_ak": "", "byteplus_sk": "",
       "byteplus_daily_cap": 5_000_000, "byteplus_free_quota": 5_000_000,
       "byteplus_img_quota": {}, "byteplus_img_used": {}}


def order(cfg, model):
    return [n for n, k, f in M.Api._seedance_keys(cfg, model)]


print("=== ① 영상 — 오늘 덜 쓴 계정이 먼저 온다")
cfg = dict(CFG,
           byteplus_used={KID[1]: 4_000_000, KID[2]: 100_000, KID[3]: 0},   # 누적은 2번이 적다
           byteplus_daily={TODAY: {KID[2]: 3_000_000}})                     # 그런데 오늘은 2번이 많다
got = order(cfg, "seedance-1-5-pro-251215")
if got and got[-1] == "계정2":
    ok(f"오늘 많이 쓴 계정이 뒤로 → {got}")
else:
    bad(f"오늘 사용량이 무시됐다 → {got}")

print("\n=== ② 어제 많이 썼어도 오늘은 처음부터")
cfg = dict(CFG, byteplus_used={KID[1]: 9_000_000},
           byteplus_daily={YDAY: {KID[1]: 5_000_000}})     # 어제 상한까지 씀
got = order(cfg, "seedance-1-5-pro-251215")
ok("어제 기록이 오늘 순서를 밀지 않는다") if len(got) == 3 else bad(f"어제 기록에 걸렸다 → {got}")

print("\n=== ③ 누적이 상한을 넘어도 오늘 안 썼으면 살아 있다")
cfg = dict(CFG, byteplus_used={KID[1]: 99_000_000}, byteplus_daily={})   # 누적 2천만% 초과
got = order(cfg, "seedance-1-5-pro-251215")
if "계정1" in got and "(소진)" not in "".join(got):
    ok("누적 초과 계정이 영구 제외되지 않는다")
else:
    bad(f"누적으로 소진 판정했다 → {got}")

print("\n=== ④ 오늘 일 상한을 채운 계정만 뒤로 밀린다")
cfg = dict(CFG, byteplus_used={}, byteplus_daily={TODAY: {KID[1]: 5_000_000}})
got = order(cfg, "seedance-1-5-pro-251215")
if got and got[-1].startswith("계정1"):
    ok(f"오늘 상한을 채운 계정이 맨 뒤 → {got}")
else:
    bad(f"오늘 상한 판정이 안 된다 → {got}")

print("\n=== ⑤ 이미지는 누적 기준 (총 장수 쿼터라 매일 안 채워진다)")
mdl = "seedream-5-0-260128"
cfg = dict(CFG, byteplus_used={}, byteplus_daily={TODAY: {KID[3]: 4_000_000}},
           byteplus_img_used={f"{KID[1]}|{mdl}": 100, f"{KID[2]}|{mdl}": 5,
                              f"{KID[3]}|{mdl}": 50})
got = order(cfg, mdl)
if got and got[0] == "계정2":
    ok(f"장수가 적은 계정이 먼저 → {got}")
else:
    bad(f"이미지가 누적 장수를 안 본다 → {got}")
# 영상 토큰을 많이 쓴 계정3이 이미지 순서에 영향을 주면 안 된다 (통이 다르다)
if got and got.index("계정3") == 1:
    ok("영상 토큰이 이미지 순서를 흔들지 않는다")
else:
    bad(f"두 쿼터가 섞였다 → {got}")

print(f"\n{'❌ 문제 ' + str(BAD) + '건' if BAD else '✅ 전 항목 통과'}")
sys.exit(1 if BAD else 0)
