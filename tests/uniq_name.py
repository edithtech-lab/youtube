"""파일 저장 규칙 검사 — 덮어쓰기 방지(_ver2) · 영상 한 편 = 폴더 하나 · 자막 빈틈 메우기.

음성은 대화상자 없이 바로 저장되므로 같은 이름이면 앞의 판이 조용히 사라진다. 그리고
소스가 저장 폴더 루트에 흩어지면 한 편을 캡컷에 올릴 때 파일을 찾아 헤맨다 — 이 파일은
그 두 가지와, 자막 사이 빈 구간(캡컷에서 클립이 잘게 끊기는 원인)을 확인한다.
"""
import sys, os, tempfile, shutil
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


print("\n[1] uniq_base — 같은 이름이면 _ver2, _ver3")
tmp = tempfile.mkdtemp(prefix="uniq_")
try:
    base = os.path.join(tmp, "음성")
    if M.uniq_base(base) != base:
        bad("빈 폴더인데 이름을 바꿨다")
    else:
        ok("겹치지 않으면 그대로 쓴다")

    open(base + ".mp3", "wb").close()
    r = M.uniq_base(base)
    if r != base + "_ver2":
        bad("mp3 가 있는데 _ver2 가 아니다 → %s" % os.path.basename(r))
    else:
        ok("mp3 가 있으면 _ver2")

    # 확장자를 가리지 않아야 한다 — wav 로 뽑을 때 mp3 판을 못 보고 지나치면 덮어쓴다
    open(base + "_ver2.wav", "wb").close()
    r = M.uniq_base(base)
    if r != base + "_ver3":
        bad("다른 확장자를 못 봤다 → %s" % os.path.basename(r))
    else:
        ok("확장자가 달라도 겹침으로 본다 (_ver3)")

    # 조각 파일(_1)·후처리본(_무음제거)도 같은 이름을 쓴다
    open(base + "_ver3_무음제거.wav", "wb").close()
    if M.uniq_base(base) != base + "_ver4":
        bad("접미사가 붙은 파일을 못 봤다")
    else:
        ok("_무음제거 같은 접미사도 겹침으로 본다")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[2] project_dir — 영상 한 편 = 폴더 하나")
tmp = tempfile.mkdtemp(prefix="proj_")
try:
    cfg = {"img_outdir": tmp}
    d = M.project_dir(cfg, "상온에 일 년을 굴려도 멀쩡한 은박 봉지")
    if not os.path.isdir(d):
        bad("폴더를 만들지 않았다")
    elif os.path.dirname(d) != tmp:
        bad("설정한 기준 폴더 밑이 아니다 → %s" % d)
    else:
        ok("기준 폴더 밑에 만든다 — %s" % os.path.basename(d))

    if not os.path.basename(d)[:8].isdigit():
        bad("폴더 이름이 날짜로 시작하지 않는다 → %s" % os.path.basename(d))
    else:
        ok("날짜로 시작해 시간순으로 정렬된다")

    # 같은 제목을 다시 부르면 같은 폴더여야 한다 — 그래야 자막·이미지가 음성 옆에 모인다
    if M.project_dir(cfg, "상온에 일 년을 굴려도 멀쩡한 은박 봉지") != d:
        bad("같은 제목인데 폴더가 달라졌다")
    else:
        ok("같은 제목이면 같은 폴더 (소스가 한곳에 모인다)")

    # 기준 폴더는 img_outdir → typecast_outdir → Downloads 순
    t2 = tempfile.mkdtemp(prefix="proj2_")
    try:
        d2 = M.project_dir({"typecast_outdir": t2}, "제목")
        if os.path.dirname(d2) != t2:
            bad("img_outdir 이 없을 때 typecast_outdir 로 안 떨어진다 → %s" % d2)
        else:
            ok("img_outdir 이 비면 typecast_outdir 을 쓴다")
    finally:
        shutil.rmtree(t2, ignore_errors=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[3] fill_gaps — 자막 사이 빈 구간")
cues = [{"start": 0.0, "end": 1.0, "text": "가"},
        {"start": 1.2, "end": 2.0, "text": "나"},     # 0.2초 빈틈 → 메운다
        {"start": 4.0, "end": 5.0, "text": "다"}]     # 2.0초 빈틈 → 그대로 둔다
out = M.fill_gaps([dict(c) for c in cues])
if out[0]["end"] != 1.2:
    bad("짧은 빈틈을 안 메웠다 → %s" % out[0]["end"])
else:
    ok("짧은 빈틈은 앞 자막을 늘려 메운다 (캡컷 클립이 안 끊긴다)")
if out[1]["end"] != 2.0:
    bad("문장 사이 긴 쉼까지 메웠다 → %s" % out[1]["end"])
else:
    ok("긴 쉼은 그대로 둔다 (끝난 말이 남아 있으면 어색하다)")

# 메운 뒤에도 순서와 길이가 깨지면 안 된다
if any(c["end"] < c["start"] for c in out) or len(out) != 3:
    bad("메우다 자막이 깨졌다")
else:
    ok("줄 수와 시간 순서가 유지된다")

print("\n" + ("❌ %d건 실패" % BAD if BAD else "✅ 전 항목 통과"))
sys.exit(1 if BAD else 0)
