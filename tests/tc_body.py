"""타입캐스트 요청 본문 검증 — 톤 고정 장치(seed·emotion·앞뒤 문맥)가 실제로 실린다."""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 콘솔이 cp949 여도 ✅/❌ 가 안 깨지게
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import main as M

BAD = 0
sent = {}


class FakeResp:
    status_code = 200
    text = ""

    @staticmethod
    def json():
        return {"audio": "", "audio_format": "mp3", "audio_duration": 3.0,
                "words": [{"text": "테스트", "start": 0.0, "end": 0.5}]}


def fake_post(url, headers=None, params=None, json=None, timeout=None):
    sent.update({"url": url, "headers": headers, "params": params, "body": json})
    return FakeResp()


M.requests.post = fake_post
api = M.Api()
CFG = {"typecast_key": "k", "typecast_voice": "tc_x", "typecast_model": "ssfm-v30",
       "typecast_tempo": 1.2, "typecast_emotion": "happy"}

api._tc_speak_one(CFG, "본문", seed=777, prev="앞 문장", nxt="뒤 문장")
b = sent["body"]
checks = [
    ("엔드포인트가 with-timestamps", sent["url"].endswith("/v1/text-to-speech/with-timestamps")),
    ("단어 단위 요청", sent["params"] == {"granularity": "word"}),
    ("API 키 헤더", sent["headers"].get("X-API-KEY") == "k"),
    ("한국어 지정", b.get("language") == "kor"),
    ("속도 반영", b["output"]["audio_tempo"] == 1.2),
    # 캡컷용 최종 소스라 무손실이 기본 — mp3 로 받으면 그 순간 한 번, 무음 제거에서 또 한 번 깎인다
    ("설정이 없으면 wav 로 받는다", b["output"]["audio_format"] == "wav"),
    ("시드 실림 (같은 대본 → 같은 톤)", b.get("seed") == 777),
    # prompt 는 preset/smart 두 모드 중 하나다 (2026-08-08 API 실측 — 섞으면 422).
    # 감정을 고르면 preset 모드이고, 이 모드는 문맥 필드를 받지 못한다.
    ("감정 고정이 preset 모드로 실림", b["prompt"].get("emotion_type") == "preset"),
    ("감정 이름은 emotion_preset 에", b["prompt"].get("emotion_preset") == "happy"),
    ("preset 모드엔 문맥을 안 실음 (섞으면 422)",
     "previous_text" not in b["prompt"] and "next_text" not in b["prompt"]),
]

# 감정을 안 고르면 smart 모드 + 앞뒤 문맥 — 덩어리 경계에서 말투가 튀는 걸 막는다
sent.clear()
api._tc_speak_one(dict(CFG, typecast_emotion=""), "본문", seed=0, prev="앞 문장", nxt="뒤 문장")
sb = sent["body"]
checks += [
    ("감정 미지정 → smart 모드", sb["prompt"].get("emotion_type") == "smart"),
    ("앞 문맥 실림", sb["prompt"].get("previous_text") == "앞 문장"),
    ("뒤 문맥 실림", sb["prompt"].get("next_text") == "뒤 문장"),
]
for name, cond in checks:
    BAD += (not cond)
    print(f" {'OK ' if cond else '❌ '} {name}")

# 감정·문맥이 없으면 prompt 를 아예 안 보낸다 (빈 값이 모델을 흔들지 않게)
sent.clear()
api._tc_speak_one(dict(CFG, typecast_emotion=""), "본문")
ok = "prompt" not in sent["body"] and "seed" not in sent["body"]
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 지정이 없으면 prompt·seed 를 안 보냄")

# 시드를 안 주면 tc_speak 가 하나 뽑아서 돌려준다 (사용자가 잠글 수 있게)
M.load_config = lambda: dict(CFG)
M.Api._concat_audio = lambda self, parts, out: None
r1 = api.tc_speak({"script": "문장 하나입니다.", "max_chars": 14})
r2 = api.tc_speak({"script": "문장 하나입니다.", "max_chars": 14, "seed": 555})
ok = r1.get("seed") and r2.get("seed") == 555
BAD += (not ok)
print(f" {'OK ' if ok else '❌ '} 시드 반환 (자동 {r1.get('seed')} · 지정 {r2.get('seed')})")

# _num 은 int 로 잘라서 0.7초·1.2배속을 0·1로 만든다 — 소수는 _fnum 을 써야 한다
for v, d, want in ((0.7, 0.7, 0.7), (1.2, 1.0, 1.2), ("3.38", 0, 3.38), (None, 0.5, 0.5),
                   ("", 0.7, 0.7), ("abc", 1.0, 1.0)):
    got = M._fnum(v, d)
    ok = abs(got - want) < 1e-9
    BAD += (not ok)
    print(f" {'OK ' if ok else '❌ '} _fnum({v!r}, {d}) = {got} (기대 {want})")

print(f"\n{'❌ ' + str(BAD) + '건 실패' if BAD else '✅ 전 항목 통과'}")
