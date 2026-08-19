# 통합 수집기 (PySide6 데스크톱 앱 · Chromium 내장 = 무설치) — 잘 팔리는 소재 발굴 + 스크립트 추출
# subprocess 를 모듈 차원에서 임포트한다 — 함수마다 지역 임포트하다 하나가 빠뜨려
# tc_respeak(문장별 다시 읽기)의 ffmpeg 호출이 NameError 로 죽었다 (2026-08-19 실사고)
import json, os, sys, threading, random, time, re, subprocess
from datetime import datetime
from urllib.parse import urljoin
import requests, urllib3, cloudscraper
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from datetime import timedelta
import yt_dlp, isodate

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
if getattr(sys, "frozen", False):
    RES_DIR = sys._MEIPASS
    APP_DIR = os.path.dirname(sys.executable)   # exe가 있는 폴더
else:
    RES_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = RES_DIR

# config 위치: 빌드된 exe는 항상 exe 옆(_internal과 같은 폴더) → 설정·자막이 앱(zip)과 함께 이동.
# 기존 %APPDATA%\collector\config.json이 있으면 최초 1회 자동 이관 (설정 유실 방지).
# 개발 실행은 프로젝트 폴더 config.json 있으면 그걸, 없으면 APPDATA 사용 (기존 동작 유지).
PORTABLE_CONFIG = os.path.join(APP_DIR, "config.json")
APPDATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "collector")
os.makedirs(APPDATA_DIR, exist_ok=True)
if getattr(sys, "frozen", False):
    BASE_DIR = APP_DIR
    CONFIG_FILE = PORTABLE_CONFIG
    _old_cfg = os.path.join(APPDATA_DIR, "config.json")
    if not os.path.exists(CONFIG_FILE) and os.path.exists(_old_cfg):
        try:
            import shutil
            shutil.copy2(_old_cfg, CONFIG_FILE)
        except Exception:
            pass
elif os.path.exists(PORTABLE_CONFIG):
    BASE_DIR = APP_DIR
    CONFIG_FILE = PORTABLE_CONFIG
else:
    BASE_DIR = APPDATA_DIR
    CONFIG_FILE = os.path.join(APPDATA_DIR, "config.json")

# 컷 분해 작업 임시저장 — 앱을 껐다 켜도 이미지 탭 작업이 이어지게
DRAFT_FILE = os.path.join(os.path.dirname(CONFIG_FILE) or ".", "컷작업_임시저장.json")

# 항상 최신 flash를 가리키는 별칭 → 특정 버전 폐지(404) 회피
GEMINI_MODEL = "gemini-flash-latest"

DEFAULT_CONFIG = {
    "gemini_key": "", "apify_token": "", "youtube_api_key": "",
    "byteplus_key": "", "byteplus_key_free": "", "byteplus_prefer": "free",
    "byteplus_free_keys": "", "byteplus_used": {},   # 무료 키 여러 개(줄바꿈) · 키별 토큰 사용량(잔여 추정용)
    # 데이터 협업 보상 캠페인 — 접근 지점(ep-…)으로 호출해야 다음 날 무료 토큰이 지급된다
    "byteplus_eps": "", "byteplus_ep_base": "seedance-1-5-pro-251215", "byteplus_ep_audio": "1",
    "byteplus_free_quota": 5000000,          # 계정당 무료 '영상' 토큰 (상시 500만 + 초기 200만은 1회성)
    "byteplus_ak": "", "byteplus_sk": "",   # 잔량 조회용(관리 API). 생성은 ark- 키를 쓴다
    "byteplus_daily": {},                    # 날짜별 사용 토큰 — 보상 한도 대비 표시용
    "byteplus_daily_cap": 5000000,           # 데이터 협업 보상 일 상한
    "byteplus_img_used": {},                 # {키꼬리|모델: 장수} — 이미지는 장 단위라 따로 센다
    "byteplus_img_quota": {},                # 모델별 무료 장수 덮어쓰기 (비우면 SEEDREAM_QUOTA)
    "byteplus_on_empty": "paid",             # 무료 소진 시: paid=유료로 계속 / stop=중단
    "byteplus_rotate": "spread",             # 계정 사용: spread=덜 쓴 계정부터(보상 최대) / spend=순차 소진
    "dl_outdir": "",                         # 영상 다운로더 저장 폴더 (비우면 기본 Downloads)
    "char_sheet": "",                        # 캐릭터 시트 이미지 경로 (anime 톤 — 인물 일관성)
    # 강조 기본값 = 자동. 컷 성격에 따라 켜고 끄며(설명 컷만), 톤에 맞는 판을 고른다
    # — 3D·다큐는 계측 HUD, 와이드·전경은 발광, anime 는 만화 기호. 상한(anno_max_cuts)도 함께 걸린다
    "img_anno": "auto",                      # 이미지 주석 레이어: '' | shape | full | auto
    "img_anno_color": "auto",                # 주석 강조색: auto | red | cyan | amber | lime | white
    "vid_anno": "auto",                      # 영상 주석 애니메이션: '' | auto | draw | animate
    # 한 영상에서 강조를 켤 컷 수 상한. 0 = 무제한 — **기본값이다**.
    # 상한을 걸면 동급일 때 컷 번호가 큰 쪽부터 꺼져(_rank tie-break) 후반의 회수 컷이
    # 먼저 죽는다. 분해 지침이 이미 "한 영상 3~4컷만"을 지시하고 실측(2026-08-14 「모아이」
    # 17컷)에서 Opus 가 정확히 4컷만 켰으므로, 개수는 분해기 판단에 맡긴다.
    # 분해기가 남발하기 시작하면(5컷 이상) 화면에서 4로 되돌리면 된다.
    "anno_max_cuts": 0,
    # ── 타입캐스트 TTS (api.typecast.ai) — 음성과 '단어별 타임스탬프'를 함께 받는다.
    # 타임스탬프가 실측이라 자막 타이밍을 추정할 필요가 없다.
    "typecast_key": "",                      # X-API-KEY (studio.typecast.ai/developers/api)
    "typecast_voice": "",                    # voice_id (tc_… / uc_…)
    "typecast_voice_name": "",               # 화면 표시용
    "typecast_model": "ssfm-v30",
    "typecast_tempo": 1.0,                   # 말 속도 0.5~2.0 — SRT 타임스탬프에 그대로 반영된다
    "typecast_outdir": "",
    "typecast_lufs": -14,                   # 음량 통일 기준 (유튜브 정규화 값)
    "typecast_format": "wav",                # 받을 형식 wav(무손실·캡컷용) | mp3(1/10 용량)
    "tc_trim_wav": True,                     # 무음 제거 기본 무손실 — mp3 재인코딩 손실을 피한다
    # 톤 흔들림 대책 — 사이트에서 문장별로 톤이 달라 재생성하게 되는 걸 막는다
    "typecast_seed": 0,                      # 0=매번 랜덤 / 고정하면 같은 대본은 같은 음성
    "typecast_emotion": "",                  # 감정 고정 (빈 값이면 스마트 이모션 — 문맥 연기, 문장마다 흔들릴 수 있음)
    "typecast_smart": 0,                     # UI 스마트이모션 체크박스 기억용 — 합성은 emotion 빈 값 여부로 판단
    # ── 대본 스튜디오 (Claude API) ──
    "anthropic_key": "",                     # console.anthropic.com API 키
    "lm_model_topic": "claude-opus-5",       # 주제 추천 모델
    "lm_model_script": "claude-opus-5",      # 대본 생성 모델
    "brightdata_proxy_user": "", "brightdata_proxy_pass": "",
    "brightdata_unlocker_key": "", "brightdata_unlocker_zone": "web_unlocker2",
    # 도우인·샤오홍슈처럼 게스트 쿠키를 요구하는 사이트용 (빈 값이면 쿠키 없이 시도)
    # 예: "edge" / "chrome" / "firefox" / "whale" — '다운로더\cookies.txt'가 있으면 그쪽이 우선
    "cookie_browser": "",
    # ── 이미지 생성 탭 (PRD_이미지생성탭.md v2) ──
    "img_model": "gemini-3.1-flash-image",   # 전역 모델 (개별 승급은 재생성에서만)
    "img_size": "1K",                        # 1K / 2K / 4K — 쇼츠엔 1K로도 충분, 비용 절반
    "img_provider": "gemini",                # gemini | seedream | flux (v1은 gemini만 구현)
    "img_default_mode": "ai",                # ai = 분해 직후 전 컷 생성 대상 | manual = 전부 제외로 시작
    "img_outdir": "",                        # 빈 값이면 ~/Downloads/쇼츠/<날짜_제목> (한 편 = 폴더 하나)
    "img_max_cuts": 40,                      # 1회 최대 컷 수 (비용 방어 — 잘게 쪼갤 수 있게 넉넉히)
    "img_parallel": 0,                       # 동시 생성 수. 0=자동 (Seedream: 무료 계정 수, Gemini: 2)
    "split_input": "api",                    # 컷 분해 입력: api(모델 호출) | paste(claude.ai JSON 붙여넣기)
    "split_model": "gemini",                 # 컷 분해 모델: gemini(빠름·기본) | opus(고품질·3~6분·회당 ~250원)
    "usd_krw": 1460,                         # 원화 환산용
    "img_spent": {},                         # {"2026-08": 32400} 월별 누적 사용액(원)
    "img_style": "auto",                     # 기본 톤. auto = 컷 타입별 자동 매핑
    "img_style_refs": [],                    # 톤 레퍼런스 이미지 경로 (0~3장)
    "subject_sheet": "",                     # 피사체 시트 — 컷마다 같은 사물을 유지할 기준 그림
    "registry": {},                          # 📇 등록부 — {라벨: {path, desc, kind, scope, ep}}
                                             #   인물(scope=perm)은 영구, 사물(scope=ep)은 편 단위
    "img_style_override": {},                # {"snap": "...문구..."} 톤별 덮어쓰기 (재빌드 없이 튜닝)
    # ── 영상 생성 (Veo 3.1) — 초당 과금이라 '길이'가 곧 비용이다 ──
    "vid_model": "veo-3.1-lite-generate-preview",
    "vid_res": "720p",                       # 480p/720p/1080p/4k — 모델별 지원 범위가 다르다
    "vid_secs": 4,                           # 4 / 6 / 8 만 허용 (API 제약)
    "vid_tempo": "dynamic",                  # dynamic=역동(쇼츠 기본) | calm=차분(레퍼런스 원래 템포)
    "vid_spent": {},                         # 월별 누적 영상 사용액(원) — 이미지와 분리 집계
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try: cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")))
        except Exception: pass
    return cfg


# 소재뱅크 — config.json 과 같은 폴더에 저장되어 앱(zip)과 함께 이동한다
BANK_FILE = os.path.join(os.path.dirname(CONFIG_FILE), "소재뱅크.json")


def load_bank():
    try:
        v = json.load(open(BANK_FILE, encoding="utf-8"))
        return v if isinstance(v, list) else []
    except Exception:
        return []


def save_bank(items):
    json.dump(items, open(BANK_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def save_config(cfg):
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# 병렬 이미지 생성이 config 를 읽기-수정-쓰기(사용량 기록)하므로 그 구간을 직렬화한다.
# 안 걸면 두 스레드가 같은 잔량을 읽어 카운트가 유실되고 무료 쿼터 초과 과금으로 이어진다.
_CFG_LOCK = threading.Lock()


# ── 크롤러 ──
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]


def rand_headers(ref=None):
    return {"User-Agent": random.choice(UA_POOL), "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
            "Accept-Encoding": "identity", "Referer": ref or "https://www.google.com/",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Upgrade-Insecure-Requests": "1"}


def make_proxy(cfg):
    u, p = cfg.get("brightdata_proxy_user"), cfg.get("brightdata_proxy_pass")
    if not u or not p: return None
    sid = random.randint(1, 999999)
    url = f"http://{u}-session-{sid}:{p}@brd.superproxy.io:33335"
    return {"http": url, "https": url}


# 도우인은 영상을 '페이지 이동' 없이 모달로 띄우기 때문에, 주소창을 복사하면
# 검색/유저/추천 페이지 URL + ?modal_id=<영상ID> 형태가 나온다.
# yt-dlp는 그런 페이지 URL을 모르므로 'Unsupported URL'로 실패 → 표준 /video/<id>로 교정한다.
DOUYIN_MODAL_RE = re.compile(r"[?&](?:modal_id|aweme_id|vid)=(\d{6,})")
DOUYIN_PATH_RE = re.compile(r"douyin\.com/(?:video|note|share/video)/(\d+)")


def normalize_media_url(url):
    """플랫폼별 '재생 페이지가 아닌' URL을 yt-dlp가 아는 표준 영상 URL로 변환."""
    u = (url or "").strip()
    if not u:
        return u
    if "douyin.com" in u.lower():
        m = DOUYIN_MODAL_RE.search(u) or DOUYIN_PATH_RE.search(u)
        if m:
            return f"https://www.douyin.com/video/{m.group(1)}"
    return u


def cookie_args_for(url, tooldir, cfg):
    """도우인·샤오홍슈는 게스트 쿠키가 없으면 상세 API가 닫혀 있다.
    ① '다운로더\\cookies.txt' (브라우저 확장으로 내보낸 파일) 최우선 — 가장 확실
    ② 없으면 설정의 cookie_browser에서 직접 추출
       (크롬·엣지는 최신 쿠키 암호화 때문에 실패할 수 있어 기본값은 비움)"""
    if not re.search(r"douyin\.com|xiaohongshu\.com|xhslink", url or "", re.I):
        return []
    ck = os.path.join(tooldir, "cookies.txt")
    if os.path.exists(ck):
        return ["--cookies", ck]
    b = (cfg.get("cookie_browser") or "").strip()
    return ["--cookies-from-browser", b] if b else []


def dl_error_hint(url, msg):
    """실패 원인별로 다음 행동을 알려주는 한글 안내를 덧붙인다."""
    out = f"다운로드 실패: {msg}"
    low = (msg or "").lower()
    if "unsupported url" in low:
        out += " — 영상 재생 페이지 주소가 아닙니다 (검색·프로필 목록 주소는 받을 수 없음)"
    elif re.search(r"douyin\.com", url or "", re.I) and ("cookie" in low or "login" in low):
        out += (" — 도우인은 게스트 쿠키가 필요합니다. 브라우저 확장(Get cookies.txt LOCALLY)으로 "
                "douyin.com 쿠키를 내보내 '다운로더\\cookies.txt'로 저장하세요")
    return out


def unlocker(cfg, url):
    key = cfg.get("brightdata_unlocker_key")
    if not key: raise RuntimeError("Web Unlocker 키 없음")
    r = requests.post("https://api.brightdata.com/request",
                      json={"zone": cfg.get("brightdata_unlocker_zone", "web_unlocker2"), "url": url, "format": "raw"},
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    if r.status_code != 200: raise RuntimeError(f"Unlocker {r.status_code}")
    return r.text


scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})


def _num(s):
    try: return int(re.sub(r"[^\d]", "", s or "0") or 0)
    except: return 0


def parse_qoo(html, site="더쿠"):
    soup = BeautifulSoup(html, "html.parser"); out = []
    tb = soup.select_one("table.theqoo_board_table > tbody.hide_notice")
    if not tb: return out
    for tr in tb.find_all("tr", recursive=False):
        if any(c.startswith("notice") for c in (tr.get("class") or [])): continue
        a, dt, vw = tr.select_one("td.title a"), tr.select_one("td.time"), tr.select_one("td.m_no")
        if not (a and dt and vw): continue
        cm = tr.select_one("a.replyNum")
        out.append({"title": a.get_text(strip=True), "link": urljoin("https://theqoo.net", a["href"]),
                    "date": dt.get_text(strip=True), "views": _num(vw.get_text()),
                    "comments": _num(cm.get_text() if cm else "0"), "site": site})
    return out


def parse_fmk(html, site="펨코"):
    soup = BeautifulSoup(html, "html.parser"); out = []
    for tr in soup.select("tbody > tr"):
        a = tr.select_one("td.title a"); dt = tr.select_one("td.time"); vw = tr.select_one("td.m_no")
        if "notice" in (tr.get("class") or []) or not (a and dt and vw): continue
        cm = tr.select_one("a.replyNum")
        out.append({"title": a.get_text(strip=True), "link": urljoin("https://www.fmkorea.com", a["href"]),
                    "date": dt.get_text(strip=True), "views": _num(vw.get_text()),
                    "comments": _num(cm.get_text() if cm else "0"), "site": site})
    return out


def parse_dc(html, site="디씨"):
    soup = BeautifulSoup(html, "html.parser"); out = []
    for tr in soup.select("tbody.listwrap2 tr.us-post"):
        if "icon_notice" in tr.get("data-type", ""): continue
        a, dt, vw = tr.select_one("td.gall_tit a"), tr.select_one("td.gall_date"), tr.select_one("td.gall_count")
        if not (a and dt and vw): continue
        cm = tr.select_one("span.reply_num")
        out.append({"title": re.sub(r"^\[[^\]]+\]\s*", "", a.get_text(strip=True)),
                    "link": urljoin("https://gall.dcinside.com", a["href"]),
                    "date": dt.get_text(strip=True), "views": _num(vw.get_text()),
                    "comments": _num(cm.get_text().strip("[]") if cm else "0"), "site": site})
    return out


SITES = {"더쿠": ("https://theqoo.net/hot", parse_qoo),
         "펨코": ("https://www.fmkorea.com/humor", parse_fmk),
         "디씨": ("https://gall.dcinside.com/board/lists/?id=dcbest", parse_dc)}


# ── 유튜브 ──
# 실제 브라우저 UA여야 timedtext가 429를 덜 뱉는다 (짧은 UA는 봇으로 취급됨)
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def merge_lines(lines):
    text = ""
    for line in lines:
        line = line.strip()
        if not text:
            text = line
        elif re.search(r"[.?!…]$", text):
            text += "\n" + line
        else:
            text += " " + line
    return text


def fetch_timedtext(url, tries=4):
    """유튜브 자막(timedtext) 본문을 받아온다.

    연속 호출하면 유튜브가 **HTTP 429 + HTML 오류 페이지**를 돌려준다. 예전 코드는
    status_code를 안 보고 그 HTML을 그대로 자막 파서에 넘겨서, 자막이 통째로
    비거나 뒤쪽 영상들이 조용히 누락됐다("가끔 뒤가 잘림 / 다시 뽑으면 됨"의 정체).
    → 429·5xx는 점점 길게 쉬며 재시도하고, HTML이면 자막이 아니므로 버린다.
    """
    delay = 2.0
    for _ in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": DEFAULT_UA}, timeout=(10, 30))
            if r.status_code == 200:
                body = r.text
                if body.lstrip().startswith("<"):   # HTML = 오류 페이지지 자막이 아니다
                    return None
                return body
            if r.status_code not in (429, 500, 502, 503, 504):
                return None
        except Exception:
            pass
        time.sleep(delay)
        delay *= 2
    return None


def yt_transcript(video_id, lang="ko"):
    # 자막은 player_client 를 타는데 web 계열(web/web_safari/mweb)은 2026-08-04 기준
    # automatic_captions 를 0개로 돌려준다. android/ios/tv 는 정상(157개 언어).
    # → 되는 클라이언트를 순서대로 시도한다. 유튜브가 또 막으면 다음 것이 받아준다.
    url = f"https://www.youtube.com/watch?v={video_id}"
    subs = {}
    for client in (["android"], ["ios"], ["tv"], ["web_embedded"], None):
        opts = {"skip_download": True, "quiet": True, "no_warnings": True,
                "ignoreerrors": True, "ignoreconfig": True}
        if client:
            opts["extractor_args"] = {"youtube": {"player_client": client}}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
        except Exception:
            continue
        if not info:
            continue
        subs = info.get("automatic_captions") or info.get("subtitles") or {}
        if subs:
            break
    if not subs:
        return None
    sel = next((l for l in [lang, "en"] if l in subs), None) or next((k for k in subs if k.startswith("en")), None) or list(subs)[0]
    fmts = subs[sel]
    url = next((f["url"] for f in fmts if f.get("ext") == "json3"), None) or next((f.get("url") for f in fmts if f.get("url")), None)
    if not url:
        return None
    txt = fetch_timedtext(url)
    if not txt:
        return None
    try:
        data = json.loads(txt)
        lines = [s.get("utf8", "").strip() for ev in data.get("events", []) for s in ev.get("segs", []) if s.get("utf8", "").strip()]
        return "\n".join(lines) if lines else None
    except Exception:
        # json3이 아닌 포맷(vtt/srt) 폴백. HTML은 fetch_timedtext에서 이미 걸러짐.
        return "\n".join(r for r in txt.splitlines() if "-->" not in r and r.strip()) or None


def yt_grade(views, subs):
    r = views / max(subs, 1)
    return "Great" if r >= 10 else "Good" if r >= 2 else "Normal" if r >= 0.5 else "Bad"


def resolve_channel_id(yt, raw):
    """채널 입력(UC아이디·@핸들·URL·채널명) → channelId(UC...) 견고 변환"""
    s = (raw or "").strip()
    m = re.search(r"(UC[\w-]{22})", s)  # 이미 channelId거나 /channel/UC... URL
    if m:
        return m.group(1)
    # 페이지에서 추출: URL이면 그대로, @핸들/이름이면 핸들 URL 구성
    url = s if s.startswith("http") else "https://www.youtube.com/@" + s.lstrip("@")
    try:
        html = requests.get(url, headers={"User-Agent": DEFAULT_UA}, timeout=8).text
        m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'"externalId":"(UC[\w-]{22})"', html)
        if m:
            return m.group(1)
    except Exception:
        pass
    # API 검색 폴백 (채널명으로 검색 — 100 units)
    try:
        r = yt.search().list(part="snippet", type="channel", q=s.lstrip("@"), maxResults=1).execute()
        if r.get("items"):
            return r["items"][0]["snippet"]["channelId"]
    except Exception:
        pass
    return None


def _yt_build_rows(yt, ids):
    """videoId 목록 → 상세/채널 통계 붙인 행 목록 (videos.list + channels.list, 50개당 1 unit)"""
    vids = {}
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).execute()
        for it in resp["items"]:
            sn, stt, cd = it["snippet"], it["statistics"], it["contentDetails"]
            try:
                dur = int(isodate.parse_duration(cd["duration"]).total_seconds())
            except Exception:
                dur = 0
            th = (sn["thumbnails"].get("medium") or sn["thumbnails"].get("high") or sn["thumbnails"].get("default") or {}).get("url", "")
            vids[it["id"]] = {"videoId": it["id"], "title": sn["title"], "thumb": th, "dur": dur,
                              "published": sn.get("publishedAt", "")[:10],
                              "views": int(stt.get("viewCount", 0)),
                              "likes": int(stt.get("likeCount", 0)), "comments": int(stt.get("commentCount", 0)),
                              "channelId": sn["channelId"]}
    cids = list({v["channelId"] for v in vids.values()})
    ch = {}
    for i in range(0, len(cids), 50):
        resp = yt.channels().list(part="statistics,snippet", id=",".join(cids[i:i + 50])).execute()
        for it in resp["items"]:
            s = it["statistics"]
            ch[it["id"]] = {"subs": int(s.get("subscriberCount", 0)), "name": it["snippet"]["title"],
                            "cviews": int(s.get("viewCount", 0)), "cvids": int(s.get("videoCount", 0))}
    rows = []
    for v in vids.values():
        c = ch.get(v["channelId"], {"subs": 0, "name": "", "cviews": 0, "cvids": 0})
        avg = c["cviews"] / max(c["cvids"], 1)  # 채널 평균 조회수
        outlier = round(v["views"] / max(avg, 1), 1)  # 돌연변이 배수
        rows.append({"videoId": v["videoId"], "title": v["title"], "thumb": v["thumb"], "views": v["views"],
                     "likes": v["likes"], "comments": v["comments"],
                     "subs": c["subs"], "channel": c["name"], "published": v["published"], "outlier": outlier,
                     "dur": v["dur"], "isShort": 0 < v["dur"] <= 60, "grade": yt_grade(v["views"], c["subs"]),
                     "link": f"https://www.youtube.com/watch?v={v['videoId']}"})
    return rows


def yt_collect_favorites(api_key, channels, period="7", length="전체"):
    """관심채널들의 최근 N일 영상 — 업로드 재생목록(UU...) 방식.
    search.list(100 units) 대신 playlistItems.list(1 unit) → 채널당 ~3 units.
    업로드 재생목록은 유튜브가 모든 채널에 자동 생성 (channelId의 UC → UU 치환)."""
    yt = build("youtube", "v3", developerKey=api_key)
    cutoff = None
    if period and period != "전체":
        cutoff = (datetime.utcnow() - timedelta(days=int(period))).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for c in channels:
        cid = c.get("id", "") if isinstance(c, dict) else str(c)
        if not cid.startswith("UC"):
            continue
        uploads = "UU" + cid[2:]
        token = None
        for _page in range(4):  # 채널당 최대 200개 안전 상한
            try:
                resp = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                               maxResults=50, pageToken=token).execute()
            except Exception:
                break  # 삭제/비공개 채널 → 건너뜀
            older = False
            for it in resp.get("items", []):
                cd = it["contentDetails"]
                pub = cd.get("videoPublishedAt", "")
                if cutoff and pub and pub < cutoff:
                    older = True  # 기간 밖 — 페이지 끝까지 확인 후 중단 (예약공개 순서 뒤섞임 대비)
                    continue
                ids.append(cd["videoId"])
            token = resp.get("nextPageToken")
            if older or not token or cutoff is None:
                break  # 기간 도달 · 마지막 페이지 · '전체' 모드는 최신 50개만
    rows = _yt_build_rows(yt, ids)
    if length == "숏폼":
        rows = [r for r in rows if r["isShort"]]
    elif length == "롱폼":
        rows = [r for r in rows if not r["isShort"]]
    rows.sort(key=lambda x: x["views"], reverse=True)
    return rows


def yt_collect(api_key, mode, query, max_results=60, region="한국", period="30", length="전체"):
    yt = build("youtube", "v3", developerKey=api_key)
    ids, token = [], None
    ch_id = query.strip()
    if mode == "channel":
        resolved = resolve_channel_id(yt, ch_id)
        if not resolved:
            raise RuntimeError(f"채널을 찾을 수 없습니다: {query} (채널명·@핸들·URL 확인)")
        ch_id = resolved
    extra = {"regionCode": "US", "relevanceLanguage": "en"} if region == "해외" else {"regionCode": "KR", "relevanceLanguage": "ko"}
    if period and period != "전체":
        after = (datetime.utcnow() - timedelta(days=int(period))).strftime("%Y-%m-%dT%H:%M:%SZ")
        extra["publishedAfter"] = after
    if length == "숏폼":
        extra["videoDuration"] = "short"  # 4분 미만만 (쇼츠 확보율↑ → 검색 횟수 절감)
    while len(ids) < max_results:
        q = dict(part="snippet", type="video", maxResults=50, order="viewCount", pageToken=token, **extra)
        q["channelId" if mode == "channel" else "q"] = ch_id if mode == "channel" else query.lstrip("@")
        resp = yt.search().list(**q).execute()
        for it in resp["items"]:
            ids.append(it["id"]["videoId"])
        token = resp.get("nextPageToken")
        if not token:
            break
    ids = ids[:max_results]
    rows = _yt_build_rows(yt, ids)
    # 한국 지역: 제목·채널에 한글 없는(영어권) 영상 제외 → relevanceLanguage는 힌트일 뿐이라 후처리 필요.
    # **단 채널 모드는 제외한다** — 사용자가 채널을 콕 집어 넣었는데 그 채널이 영어권이면
    # 결과가 통째로 0이 되고, 화면에는 "영상이 없다"로만 보여 원인을 알 수 없다
    # (2026-08-14 제보: @Deconstructed_Animations — 검색은 10개 나왔는데 필터가 전부 버렸다).
    # 필터의 목적은 키워드 검색에 영어권이 섞이는 걸 막는 것인데, 채널을 특정한 순간 그 목적이 사라진다.
    if region == "한국" and mode != "channel":
        rows = [r for r in rows if re.search(r"[가-힣]", r["title"] + r["channel"])]
    rows.sort(key=lambda x: x["views"], reverse=True)
    return rows


# ── 릴스 (Apify 수집 + Gemini 대사) ──
REEL_PROMPT = """이 인스타 릴스 영상을 분석해 JSON으로만 답해라. 설명 금지, JSON만.
{"hook":"첫 3초 화면자막 또는 첫 대사(한국어)","script_original":"전체 나레이션/대사 원문","script_ko":"전체 대사 자연스러운 한국어 번역","onscreen_text":"영상에 박힌 자막(한국어)","summary":"내용/구성 한 줄 요약"}"""


def _parse_json(t):
    t = re.sub(r"^```json\s*|\s*```$", "", (t or "").strip()).strip()
    try:
        return json.loads(t)
    except Exception:
        return {"hook": "", "script_original": "", "script_ko": t, "onscreen_text": "", "summary": "(파싱실패)"}


def _parse_json_list(t):
    t = re.sub(r"^```json\s*|\s*```$", "", (t or "").strip()).strip()
    try:
        v = json.loads(t)
        return v if isinstance(v, list) else []
    except Exception:
        m = re.search(r"\[.*\]", t, re.S)
        try:
            return json.loads(m.group(0)) if m else []
        except Exception:
            return []


def _parse_json_obj(t):
    t = re.sub(r"^```json\s*|\s*```$", "", (t or "").strip()).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        try:
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass
        return {"product": "", "why": (t or "")[:400], "hook": "", "structure": "", "coupang_point": ""}


# ── 소재 추천 프롬프트 (쿠팡 제품 썰튜브 기획자 관점) ──
TOPIC_YT_PROMPT = """너는 쿠팡파트너스 제품 썰튜브·제품소개 채널의 소재 기획자다.
아래는 유튜브에서 '채널 평균 대비 몇 배 터졌나(outlier=돌연변이)'와 좋아요/댓글이 높은 영상 목록이다.
이걸 보고 지금 이 니치에서 '따라 만들면 먹힐' 제품/소재 테마를 3~6개로 묶어 추천하라.
신박한 제품 소개에 어울리는 각도로. 반드시 JSON 배열로만 답하라(설명 금지).
[{"theme":"소재 테마(제품 중심, 구체적)","reason":"왜 먹히는지 근거(돌연변이·반응 언급)","hook":"추천 훅(첫 3초 대사)","products":"관련 제품/키워드","examples":["대표 영상 videoId 1~3개(위 목록에서)"]}]"""

TOPIC_COMM_PROMPT = """너는 쿠팡파트너스 제품 썰튜브 채널의 소재 기획자다.
아래는 커뮤니티 인기글 제목과 댓글수(반응도)다.
영상화하면 먹힐 '제품/떡밥 소재' 후보를 3~6개 뽑아라. 신선하고 선점 가능한 걸 우선.
반드시 JSON 배열로만(설명 금지).
[{"theme":"소재/떡밥(구체적)","reason":"왜 반응 오는지","hook":"영상 훅","products":"관련 제품/키워드","examples":["관련 글 제목 1~2개"]}]"""

TOPIC_DEEP_PROMPT = """너는 쿠팡 제품 썰튜브 대본 코치다. 아래는 잘 터진 영상들의 자막이다.
이걸 분석해 '따라 만들 대본 설계'를 JSON으로만 답하라(설명 금지).
{"product":"핵심 제품(들)","why":"왜 먹혔나(자막 근거)","hook":"첫 3초 훅","structure":"대본 골격(도입→전개→반전→CTA)","coupang_point":"쿠팡 링크 걸기 좋은 타이밍/멘트"}"""

TOPIC_KW_PROMPT = """너는 쿠팡파트너스 제품 썰튜브·신박한 제품 소개 유튜브 채널의 소재 리서처다.
유튜브에서 '터지는 제품 소재'를 검색해 찾으려 한다. 지금 검색하면 좋을 '검색 키워드'를 15개 추천하라.
주방/자취/캠핑/계절템/선물/청소/카페/차량/반려동물/사무 등 다양한 각도로, 실제 조회 잘 나오는 실전 검색어로.
반드시 JSON 배열로만(설명 금지). [{"keyword":"검색어","why":"왜 이 각도가 좋은지 짧게"}]"""


TOPIC_ANGLE_PROMPT = """너는 쇼핑 쇼츠 채널의 소재 기획자다. 아래 수집 데이터(유튜브 돌연변이 영상 또는 커뮤니티 인기글)에서
「친숙한 대상 × 의외의 각도」 공식으로 소재 후보를 4~8개 발굴하라.

[각도 렌즈 — 반드시 하나 배정]
1 몰락/부활  2 원래용도  3 한사람(장인)  4 금지/논란  5 가격미스터리  6 업계비밀  7 극단사용자  8 미담/돈쭐

[판정 5문항 — 통과 개수를 score 로]
① 한줄 요약에 "엥? 그게 진짜야?"가 나오는가 ② 초등학생~할머니까지 아는 대상인가
③ 결말을 중반까지 숨길 수 있는가 ④ 한국 시청자의 일상·지갑과 직결되는가
⑤ 소싱할 시각자료가 충분한가(과거재현·단면 등은 AI 대체 가능이면 통과)

[카테고리] 1브랜드반전 2용도반전 3변태문구 4꿀팁 5실용템 6테크가젯 7기업이슈 8시즌 9장인 10주의보 11돈쭐미담
[트랙] A(스토리) / A축약(용도반전) / B(솔루션) / C(정보경고)

[추가 임무] 각 소재가 '원리 설명 채널'(습니다체·모순 훅)로도 쓸 수 있으면
mystery 에 "여기 [A인데 B]인 ~가 있습니다" 형태 모순 훅을 1개 써라. 안 되면 빈 문자열.

반드시 JSON 배열로만(설명 금지). 흔해빠진 소재(다이슨 창업기 등 3회 이상 우려먹은 것)는 제외.
angle 속 사실 주장(유래·비화)은 아직 검증 전 가설이다 — 확신이 없으면 문장 끝에 "(설)"을 붙여
집필 단계에서 반드시 검증하게 하라. 수집 데이터에 없는 내용을 확정 사실처럼 쓰지 마라.
[{"target":"대상(친숙한 실물·브랜드)","fam":1~3,"angle":"의외의 각도 한 줄 훅","lens":1~8,
"cat":1~11,"track":"A|A축약|B|C","score":0~5,"check":"판정 근거 한 줄","season":"시즌 태그 or 빈값",
"mystery":"원리채널용 모순 훅 or 빈값","evidence":"수집 데이터 속 근거(제목·수치)"}]"""


def crawl_community(cfg, sites, pages=1, use_proxy=True):
    """커뮤니티 인기글 rows 반환 (소재추천 커뮤니티 모드용, _crawl과 별개)"""
    rows = []
    for site in sites:
        if site not in SITES:
            continue
        base, parser = SITES[site]
        prev = base
        for page in range(1, pages + 1):
            sep = "&" if "?" in base else "?"
            url = base if page == 1 else f"{base}{sep}page={page}"
            for attempt in range(1, 4):
                try:
                    if "theqoo.net" in base and attempt >= 2:
                        html = unlocker(cfg, url)
                    else:
                        r = scraper.get(url, headers=rand_headers(prev),
                                        proxies=make_proxy(cfg) if use_proxy else None, timeout=15, verify=False)
                        html = r.text
                    got = parser(html, site)
                    if got:
                        rows.extend(got)
                        prev = url
                        break
                except Exception:
                    time.sleep(random.uniform(1.5, 3))
            time.sleep(random.uniform(1.2, 2.5))
    return rows


# ── 네이버 데이터랩 (쇼핑인사이트 인기검색어) ──
_DL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://datalab.naver.com/shoppingInsight/sCategory.naver",
    "Origin": "https://datalab.naver.com", "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*", "Accept-Language": "ko-KR,ko;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _load_datalab_cats():
    try:
        data = json.load(open(os.path.join(RES_DIR, "categories.json"), encoding="utf-8"))
    except Exception:
        return [], {}
    idx = {}
    def walk(nodes):
        for n in nodes:
            idx[n["cid"]] = n
            walk(n.get("children") or [])
    tree = data.get("tree") or []
    walk(tree)
    return tree, idx


DL_TREE, DL_IDX = _load_datalab_cats()


def datalab_children(cid):
    nodes = (DL_IDX.get(cid, {}).get("children") if cid else DL_TREE) or []
    return [{"cid": n["cid"], "name": n["name"], "leaf": n.get("leaf", False)} for n in nodes]


def datalab_leaves(cid):
    """cid 아래 모든 말단(leaf) 카테고리 cid 리스트 (2·3·4분류 조합)"""
    node = DL_IDX.get(cid)
    roots = [node] if node else []
    out = []
    def walk(nodes):
        for n in nodes:
            ch = n.get("children") or []
            if ch:
                walk(ch)
            else:
                out.append(n["cid"])
    walk(roots)
    return out


def datalab_keywords(cid, count=40, progress=None):
    end = datetime.now()
    start = end - timedelta(days=30)
    out = []
    total_pages = max(1, (count + 19) // 20)
    for page in range(1, total_pages + 1):
        if progress:
            progress(page, total_pages)
        body = {"cid": cid, "timeUnit": "date", "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"), "age": "", "gender": "", "device": "",
                "page": str(page), "count": "20"}
        try:
            j = requests.post("https://datalab.naver.com/shoppingInsight/getCategoryKeywordRank.naver",
                              data=body, headers=_DL_HEADERS, timeout=15).json()
        except Exception:
            break
        ranks = j.get("ranks") or j.get("keywordList") or j.get("list") or j.get("data") or []
        if not ranks:
            break
        for it in ranks:
            kw = it.get("keyword")
            if kw:
                out.append(kw)
        time.sleep(0.4)
    return out[:count]


def apify_reels(token, username, count):
    u = username.strip()
    if u.startswith("http"):
        # /reels, /reel, /tagged 등 탭 접미사·쿼리 제거 → 깨끗한 프로필 URL
        base = re.split(r"/(reels?|tagged|followers|following)\b", u, flags=re.I)[0].split("?")[0].rstrip("/")
        profile_url = base + "/"
    else:
        profile_url = f"https://www.instagram.com/{u.lstrip('@')}/"
    url = f"https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items?token={token}"
    fetch = max(count * 3, 12)  # 이미지 게시물이 섞이므로 넉넉히 가져와 영상만 추림
    body = {"directUrls": [profile_url], "resultsType": "posts", "resultsLimit": fetch}
    r = requests.post(url, json=body, timeout=400)
    if not (200 <= r.status_code < 300):  # Apify는 200/201 모두 정상
        raise RuntimeError(f"Apify {r.status_code}: {r.text[:200]}")
    items = r.json()
    if isinstance(items, dict):  # 에러 객체가 오는 경우
        raise RuntimeError(f"Apify 응답 오류: {str(items)[:200]}")
    reels = []
    for i in items:
        v = i.get("videoUrl")
        thumb = i.get("displayUrl", "")
        if not v:  # Sidecar(캐러셀) 내부에 영상이 있으면 첫 영상 사용
            for c in (i.get("childPosts") or i.get("sidecarItems") or []):
                if c.get("videoUrl"):
                    v = c.get("videoUrl"); thumb = c.get("displayUrl", thumb); break
        if not v:
            continue
        reels.append({"url": i.get("url", ""), "videoUrl": v, "thumb": thumb,
                      "caption": i.get("caption", ""), "likes": i.get("likesCount", 0),
                      "views": i.get("videoViewCount") or i.get("videoPlayCount") or 0})
    return reels[:count]


def apify_post_video(token, post_url):
    """인스타 게시물/릴 URL → 직접 mp4 URL. yt-dlp는 비로그인 인스타 접근이 차단되므로 Apify로 우회."""
    clean = post_url.split("?")[0].rstrip("/") + "/"
    url = f"https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items?token={token}"
    body = {"directUrls": [clean], "resultsType": "posts", "resultsLimit": 1}
    r = requests.post(url, json=body, timeout=400)
    if not (200 <= r.status_code < 300):  # Apify는 200/201 모두 정상
        raise RuntimeError(f"Apify {r.status_code}: {r.text[:200]}")
    items = r.json()
    if isinstance(items, dict):
        raise RuntimeError(f"Apify 응답 오류: {str(items)[:200]}")
    for i in items:
        v = i.get("videoUrl")
        if not v:  # 캐러셀이면 내부 첫 영상
            for c in (i.get("childPosts") or i.get("sidecarItems") or []):
                if c.get("videoUrl"):
                    v = c.get("videoUrl"); break
        if v:
            return v
    raise RuntimeError("게시물에서 영상을 찾지 못했습니다 (이미지 게시물·비공개·삭제 여부 확인)")


# ══════════════════════════════════════════════════════════════════
# 이미지 생성 탭 (PRD_이미지생성탭.md v2 — 스크립트 → 소스 이미지 전량 생성)
# ══════════════════════════════════════════════════════════════════
GEMINI_REST = "https://generativelanguage.googleapis.com/v1beta"

# USD, 장당. 공식 가격표 기준 (2026-07-29 확인) — PRD 7.1.1 표와 같이 갱신할 것
PRICE_USD = {
    # ⚠ 여기에 없는 (모델, 해상도) 조합은 UI 에도 안 뜬다 — IMG_SIZES_BY_MODEL 과 짝이다.
    #   실제로 API 가 받지 않는 조합을 넣어두면 사용자가 고를 수 있게 되고 그대로 실패한다
    #   (2026-08-15 실측: lite 에 2K·4K, Seedream 5.0 Lite 에 1K 가 그런 유령 조합이었다).
    ("gemini-3.1-flash-lite-image", "1K"): 0.0336,   # 공식: 1K 전용
    ("gemini-3.1-flash-image", "1K"): 0.067,
    ("gemini-3.1-flash-image", "2K"): 0.101,
    ("gemini-3.1-flash-image", "4K"): 0.151,
    # Seedream — 장당 과금이라 해상도와 무관하게 동일 (콘솔 실측 2026-08-06)
    # Pro 단가는 콘솔에 안 떠서 4.5 기준을 임시로 넣었다 — 실제 청구가 다르면 고쳐야 한다
    ("dola-seedream-5-0-pro-260628", "2K"): 0.040,
    ("dola-seedream-5-0-pro-260628", "4K"): 0.040,
    ("seedream-5-0-260128", "2K"): 0.035,            # API 실측: 2k·3k·4k (1k 없음)
    ("seedream-5-0-260128", "3K"): 0.035,
    ("seedream-5-0-260128", "4K"): 0.035,
    ("seedream-4-5-251128", "1K"): 0.040,            # API 실측: 1k·2k·4k (3k 없음)
    ("seedream-4-5-251128", "2K"): 0.040,
    ("seedream-4-5-251128", "4K"): 0.040,
    ("gemini-3-pro-image", "1K"): 0.134,
    ("gemini-3-pro-image", "2K"): 0.134,
    ("gemini-3-pro-image", "4K"): 0.24,
}
# 모델별로 **실제 API 가 받는** 해상도. 2026-08-15 확정:
#   · Gemini  — 공식 문서. 대문자 K 만 받는다("1k" 는 거부). lite 는 1K 전용,
#               flash 는 0.5K 도 있으나 쇼츠에 쓸 일이 없어 뺐다
#   · Seedream — API 에 잘못된 값을 던져 에러 메시지에서 캐냈다(비용 0). **소문자** 를 받는다.
#               세대마다 다르다: 5.0 Lite = 2k·3k·4k / 4.5 = 1k·2k·4k
# 사용자가 모델을 고르면 이 목록으로 해상도 셀렉트를 다시 그린다 — 예전엔 해상도가 먼저라
# 지원하지 않는 조합을 고를 수 있었고, 그대로 API 에 나가 실패했다.
IMG_SIZES_BY_MODEL = {
    "gemini-3.1-flash-lite-image": ["1K"],
    "gemini-3.1-flash-image":      ["1K", "2K", "4K"],
    "gemini-3-pro-image":          ["1K", "2K", "4K"],
    "dola-seedream-5-0-pro-260628": ["2K", "4K"],
    "seedream-5-0-260128":         ["2K", "3K", "4K"],
    "seedream-4-5-251128":         ["1K", "2K", "4K"],
}
# label = 구글 공식 표시명(2026-08-04 API 조회 확인). 'Nano Banana' 가 이 모델들의 별칭이다.
# 모델 ID를 라벨에 같이 노출해야 어느 버전인지 사용자가 안다.
IMG_MODELS = [
    {"id": "gemini-3.1-flash-lite-image", "label": "Nano Banana 2 Lite", "note": "톤 테스트·초벌 (1K 전용)"},
    {"id": "gemini-3.1-flash-image", "label": "Nano Banana 2", "note": "권장 · 실제 컷 생산"},
    {"id": "gemini-3-pro-image", "label": "Nano Banana Pro", "note": "훅·핵심 컷"},
    # ⚠ id 에 날짜가 빠져 있어 계속 404 였다 (2026-08-15 /models 조회로 확정).
    #   고친 뒤에도 이 계정은 "has not activated the model" 이라 콘솔에서 활성화가 먼저다.
    {"id": "dola-seedream-5-0-pro-260628", "label": "Seedream 5.0 Pro",
     "note": "⚠ 콘솔에서 모델 활성화 필요 · 최상위 화질"},
    {"id": "seedream-5-0-260128", "label": "Seedream 5.0 Lite", "note": "🎁 무료 528장 · 2K~4K"},
    {"id": "seedream-4-5-251128", "label": "Seedream 4.5", "note": "🎁 무료 533장 · 이전 세대"},
]
# Seedream 의 size 는 **비율과 해상도를 동시에** 결정한다.
# ⚠ '2k' 같은 티어 문자열만 보내면 비율 정보가 사라져 모델이 제멋대로 정한다
#   (2026-08-16 실사고: 9:16 을 요청했는데 2848x1600·2048x2048 이 나왔다).
#   그래서 항상 WIDTHxHEIGHT 로 보낸다 — 티어는 아래 표에서 픽셀로 바꿔 쓴다.
# 최소 픽셀(약 369만) 제한이 있어 1K 는 Seedream 에서 쓰지 않는다.
# 최대 16,777,216px(4096²) 제한 — 4K 9:16 은 2880x5120 = 14.7M 으로 그 아래다.
SEEDREAM_SIZES = {"9:16": (1440, 2560), "16:9": (2560, 1440), "1:1": (1920, 1920)}
SEEDREAM_SIZE_BY_TIER = {
    "1K": {"9:16": (720, 1280),  "16:9": (1280, 720),  "1:1": (960, 960)},
    "2K": {"9:16": (1440, 2560), "16:9": (2560, 1440), "1:1": (1920, 1920)},
    "3K": {"9:16": (2160, 3840), "16:9": (3840, 2160), "1:1": (2880, 2880)},
    "4K": {"9:16": (2880, 5120), "16:9": (5120, 2880), "1:1": (3840, 3840)},
}


def seedream_size(tier, aspect):
    """티어+비율 → 'WIDTHxHEIGHT'. 표에 없으면 2K 기준으로 떨어진다."""
    t = (tier or "").strip().upper()
    tbl = SEEDREAM_SIZE_BY_TIER.get(t) or SEEDREAM_SIZE_BY_TIER["2K"]
    w, h = tbl.get(aspect) or tbl.get("9:16")
    return f"{w}x{h}"
# 계정당 무료 '장수' (콘솔 실측 2026-08-06) — 영상 토큰 쿼터와 완전히 별개다
SEEDREAM_QUOTA = {"dola-seedream-5-0-pro-260628": 100,
                  "seedream-5-0-260128": 528, "seedream-4-5-251128": 533}
# 참고 — 키로 열려 있으나 이 앱에서 쓰지 않는 이미지 모델 (2026-08-04 조회):
#   gemini-2.5-flash-image        = Nano Banana (1세대). 1024px 제한·구형이라 제외
#   *-preview 계열                = 위 모델들의 프리뷰 별칭. 정식 ID를 쓴다
#   nano-banana-pro-preview       = gemini-3-pro-image 와 동일 모델의 별칭
#   imagen-4.0-generate-001 등    = Imagen 4 계열. **generateContent 가 아니라 predict 엔드포인트**라
#                                   현재 _gen_gemini 로는 호출 불가. 쓰려면 별도 어댑터가 필요하다.


def _num(v, d):
    try: return int(float(v))
    except Exception: return d


def _fnum(v, d):
    """소수를 지키는 _num. _num 은 int 로 잘라서 0.7초·1.2배속이 0·1이 된다 (2026-08-06)."""
    try:
        f = float(v)
    except Exception:
        return float(d)
    return f if f == f and abs(f) != float("inf") else float(d)   # NaN·inf 차단


# 컷 분해(LLM) 단가 — USD / 100만 토큰. (입력, 출력)
# Claude 는 공식 가격표 기준. Gemini 는 단가가 자주 바뀌므로 config 의 split_price_usd 로
# 덮어쓸 수 있게 뒀다 ({"gemini": [입력, 출력]} 형식).
# 추정이 아니라 **응답이 알려준 실제 토큰 수**로 계산하므로 단가만 맞으면 값이 정확하다.
LLM_PRICE_USD = {
    "opus": (5.0, 25.0),        # claude-opus-5
    "gemini": (0.30, 2.50),     # Gemini 3.1 Flash (추정 — 콘솔 단가로 덮어쓰세요)
}


def split_cost_krw(cfg, kind, tin, tout):
    """컷 분해 1회 비용(원). 토큰 수는 API 응답이 준 실측값이다."""
    ov = (cfg.get("split_price_usd") or {}).get(kind)
    pin, pout = (ov if isinstance(ov, (list, tuple)) and len(ov) == 2
                 else LLM_PRICE_USD.get(kind, (0.0, 0.0)))
    usd = (_fnum(tin, 0) * _fnum(pin, 0) + _fnum(tout, 0) * _fnum(pout, 0)) / 1_000_000
    return round(usd * _num(cfg.get("usd_krw"), 1460))


def price_krw(cfg, model, size):
    usd = PRICE_USD.get((model, size), 0)
    return round(usd * _num(cfg.get("usd_krw"), 1460))


# ── 영상 생성 (Veo 3.1) ──────────────────────────────────────────
# 이미지와 달리 **초당 과금**이라 길이가 곧 비용이다. 누르기 전에 초×단가가 보여야 한다.
# 공식 가격표 ai.google.dev/gemini-api/docs/pricing (2026-08-04 조회) · 오디오 포함
VIDEO_PRICE_USD = {
    ("veo-3.1-lite-generate-preview", "720p"): 0.05,
    ("veo-3.1-lite-generate-preview", "1080p"): 0.08,
    ("veo-3.1-fast-generate-preview", "720p"): 0.10,
    # 공식 문서 대조(2026-08-19, ai.google.dev/gemini-api/docs/pricing): fast 1080p 는 $0.12
    # (0.10 으로 잘못 적혀 있었다 — 예상가가 실청구보다 싸게 보이던 원인)
    ("veo-3.1-fast-generate-preview", "1080p"): 0.12,
    ("veo-3.1-fast-generate-preview", "4k"): 0.30,
    ("veo-3.1-generate-preview", "720p"): 0.40,
    ("veo-3.1-generate-preview", "1080p"): 0.40,
    ("veo-3.1-generate-preview", "4k"): 0.60,
    # Seedance (BytePlus ModelArk) — 토큰 과금(W×H×24fps×초/1024)을 초당으로 환산.
    # 실측(2026-08-05): 1.0 pro 480p 5초 = 49,005토큰, 1.5 pro(오디오 포함) = 50,638토큰 — 단가 사실상 동일.
    # 공식 초당가: 1.5 pro $0.023/s(480p, OpenRouter 2026-08-05). 오디오를 켜도 토큰 차이 미미.
    ("seedance-1-0-pro-250528", "480p"): 0.025,
    ("seedance-1-0-pro-250528", "720p"): 0.054,
    ("seedance-1-0-pro-250528", "1080p"): 0.122,
    # 콘솔 실단가(2026-08-10 확인): 무음 $0.0012/K · 유음 $0.0024/K 토큰.
    # 초당 토큰 = 가로×세로×24fps/1024. 나레이션을 따로 얹으므로 **무음 기준**으로 잡는다
    # (설정에서 '장면 효과음'을 켜면 실제 청구는 두 배가 된다).
    ("seedance-1-5-pro-251215", "480p"): 0.0115,
    ("seedance-1-5-pro-251215", "720p"): 0.0259,
    ("seedance-1-5-pro-251215", "1080p"): 0.0583,
}
VIDEO_MODELS = [
    {"id": "veo-3.1-lite-generate-preview", "label": "Veo 3.1 Lite", "note": "권장 · 가장 저렴", "engine": "veo"},
    {"id": "veo-3.1-fast-generate-preview", "label": "Veo 3.1 Fast", "note": "중간 · 4K 가능", "engine": "veo"},
    {"id": "veo-3.1-generate-preview", "label": "Veo 3.1 표준", "note": "최고 품질 · 8배 비쌈", "engine": "veo"},
    {"id": "seedance-1-0-pro-250528", "label": "Seedance 1.0 Pro", "note": "체인 강함 · 무음 · 12초 가능", "engine": "seedance"},
    {"id": "seedance-1-5-pro-251215", "label": "Seedance 1.5 Pro", "note": "체인+효과음 · 12초 · 1.0과 같은 값", "engine": "seedance"},
]
# Seedance 는 --duration 으로 2~12초 자유 — 쇼츠에 쓸 만한 값만 노출
SEEDANCE_SECONDS = [4, 5, 6, 8, 10, 12]
# API가 허용하는 값 (2026-08-04 실측). 오류 문구는 "between 4 and 8, inclusive" 라고 하지만
# 5초·7초도 거부된다 → 실제로는 짝수 3개만 유효. 2초·3초는 불가.
VIDEO_SECONDS = [4, 6, 8]
# 해상도별 허용 길이 (2026-08-04 실측). 720p 외에는 8초 고정이라 비용이 2배로 뛴다.
#   "1080p is not supported for a duration of 4 seconds." / lite 는 4k 자체를 지원 안 함
VIDEO_SECS_BY_RES = {"720p": [4, 6, 8], "1080p": [8], "4k": [8]}
# 실제 셀렉트는 모델별 가격표에서 그린다(vidResOpts) — 이 목록은 폴백·참고용이다.
# 480p 는 Seedance 전용이고 720p 의 절반 이하 단가라 톤·모션 시험에 쓴다.
VIDEO_RES = ["480p", "720p", "1080p", "4k"]


def seedance_audio_mult(cfg, model, audio=None):
    """Seedance 는 오디오를 만들면 토큰 단가가 정확히 두 배다.
    공식 대조(2026-08-19): 무음 $1.2/M · 유음 $2.4/M 토큰 — 콘솔 실단가(08-10)와 일치.
    표에는 무음 기준을 담고, '장면 효과음'이면 2배로 올린다.
    audio 를 넘기면 그 값을(배치의 실제 선택), 안 넘기면 설정값을 본다 —
    배치가 설정과 다른 소리 모드로 돌 때 정산이 어긋나지 않게."""
    if not str(model).startswith(("seedance", "ep-")):
        return 1.0                      # Veo 는 오디오 포함 단가라 배수를 안 곱한다
    a = audio if audio is not None else (cfg.get("vid_audio") or "room")
    return 2.0 if a == "sfx" else 1.0


def video_price_krw(cfg, model, res, secs, audio=None):
    usd = VIDEO_PRICE_USD.get((model, res))
    if usd is None and str(model).startswith("ep-"):
        # 접근 지점은 뒤에 붙은 모델이 무엇인지 알 수 없다 → 설정에서 고른 기준 모델 단가로 계산
        usd = VIDEO_PRICE_USD.get(((cfg.get("byteplus_ep_base") or "seedance-1-5-pro-251215"), res))
    if usd is None:
        return 0
    usd *= seedance_audio_mult(cfg, model, audio)
    return round(usd * _num(secs, 4) * _num(cfg.get("usd_krw"), 1460))


# 영상 프롬프트 = 이미지 프롬프트 + 「카메라」 + 「시간에 따른 변화」.
# 레퍼런스 채널 역추적 결과 이 두 축이 정지컷과 영상컷을 가르는 핵심이었다.
# 이미지가 없을 때(T2V) — 공식 5요소 순서: 촬영(카메라·구도)을 맨 앞에 둔다.
MOTION_PROMPT = """{shot_line}Camera: {camera}

SUBJECT: {scene}
Motion: {motion}
The motion is already underway on the very first frame — never open on a frozen,
settling shot.

{style}

{tempo}

{audio}
{negative}"""
CAMERA_PRESETS = {
    # 카메라는 '어느 방향으로 움직이는가'만 말한다. 빠르기는 VIDEO_TEMPO 가 담당한다 —
    # 프리셋에 very slow 를 박아두면 역동 모드와 자기모순이 난다.
    "push": "dolly push-in, the frame closing in over the shot",
    "pull": "dolly pull-back, gradually revealing more of the surroundings",
    "down": "camera travels downward across the frame",
    "up": "camera travels upward across the frame",
    "panright": "camera glides to the right, the framing sliding sideways",
    "panleft": "camera glides to the left, the framing sliding sideways",
    "pushdown": "push-in while drifting downward at the same time, "
                "closing in as the framing travels down",
    "pullup": "pull-back while rising upward at the same time, "
              "opening out as the framing lifts",
    "orbit": "orbit, the viewpoint arcing around what is in frame",
    "still": "locked-off camera, no camera movement",
    # 강조가 붙은 컷에 쓰면 안 되는 워크 — 대상을 프레임 밖으로 밀어내거나 시선을 뺏는다.
    # (아래 CAMERA_LOUD 로 걸러진다)
    # 강조 그래픽이 붙은 컷용 — 움직이되 대상을 프레임 밖으로 밀어내지 않는다 (2026-08-12).
    # 완전 고정은 쇼츠에서 정지화면처럼 보이므로, 아주 느린 전진으로 생기만 준다.
    "slowpush": ("very slow, barely perceptible dolly push-in — the framing tightens only "
                 "a little over the whole shot, and whatever is marked stays fully in frame "
                 "the entire time, never drifting toward or past the edge"),
    # slowpush 의 좌우판 — 인물이 셋 이상인 컷에서 오빗은 인원수·배치를 무너뜨리지만
    # 이 정도 이동폭은 유지된다 (실측 2026-08-15). 강조 컷에서도 안전하다.
    "slowslide": ("very slow, barely perceptible sideways slide — the framing drifts only a "
                  "little across the whole shot, and everything in frame keeps its exact size, "
                  "position and count, never drifting toward or past the edge"),
    # ── 역동 그룹 — 속도감이 워크의 정체성이라 예외적으로 빠르기를 프리셋에 포함한다 ──
    "crash": "fast crash zoom-in, rushing toward the subject with real urgency",
    "whip": "quick whip pan, the frame snapping sideways to land on the subject",
    "handheld": "energetic handheld tracking shot, chasing the subject with natural sway and drive",
    "riseorbit": "low-angle rise combined with an orbital arc, sweeping up and around the subject",
    "hyperlapse": "hyperlapse push, the camera rushing forward through the scene as time streaks by",
    "fpv": "FPV racing-drone shot, diving and weaving through the scene with fast swooping agility",
    "dollyzoom": "dolly zoom vertigo effect — pushing in on the subject while the background "
                 "stretches and falls away behind it",
    "whiptilt": "quick whip tilt, the frame snapping vertically to land on the subject",
    "roll": "dutch roll, the horizon tilting and rotating as the camera keeps moving",
    "chase": "chase cam racing right behind the subject as it moves through the scene",
    "gamecam": "smooth third-person follow camera tracking a few meters behind the character "
               "at shoulder height, steady and locked to their pace, exactly like open-world "
               "gameplay footage",
    "sweeparc": "fast sweeping arc around the subject from left to right — the subject stays "
                "centered and locked while the background wheels past behind it",
    # ── 2026-08-12 추가 ────────────────────────────────────────────────
    # 좁은 틈을 지나 내부로 들어가는 워크. 이 채널 콘텐츠(통로·배관·단면)에 자주 필요하다.
    "needle": "the camera slips through a narrow opening — a gap, slot, doorway or crack barely "
              "wider than the lens — and continues into the space beyond in one unbroken move, "
              "the walls of the opening rushing past close on either side as it passes through",
    # 훅 전용 — 피사체는 멈춘 듯 느리고 카메라만 빠르게 돈다
    "bullettime": "bullet-time orbit: the action in the scene is almost frozen, drifting in "
                  "extreme slow motion, while the camera races around it at high speed, "
                  "circling the subject and holding it locked at the centre of frame",
    # 전환용 — 회전 블러로 화면을 지우고 다음 장면을 연다 (체인 컷의 매개 구간)
    "whiproll": "the camera whips into a fast roll, the whole frame spinning and smearing into "
                "rotational motion blur, then settles as the spin slows — the blur at the peak "
                "of the turn is strong enough to wash the framing out completely",
}
# 강조(치수선·화살표 등)가 붙은 컷에서 금지되는 워크. 대상을 프레임 밖으로 밀어내거나
# 회전·흔들림으로 그래픽의 원근 고정을 깨뜨린다. still·slowpush 로 강등된다.
CAMERA_LOUD = {"push", "pushdown", "crash", "whip", "whiptilt", "handheld", "hyperlapse",
               "fpv", "dollyzoom", "roll", "chase", "sweeparc", "riseorbit", "orbit",
               "gamecam", "pull", "pullup",
               # 신규 3종도 전부 금지 — 통과·공전·회전블러는 그래픽을 프레임 밖으로
               # 밀어내거나 원근 고정을 깨뜨린다 (Flow 자문 2026-08-12 와 실측이 일치)
               "needle", "bullettime", "whiproll"}

CAMERA_LABELS = {"auto": "자동 (장면에 맞춰)",
                 "push": "다가감", "pull": "물러남",
                 "down": "아래로 훑음", "up": "위로 훑음",
                 "panright": "오른쪽으로", "panleft": "왼쪽으로",
                 "pushdown": "다가가며 아래로", "pullup": "물러나며 위로",
                 "orbit": "공전 (피사체 중심 · 빠르기는 움직임 설정)", "still": "고정",
                 "slowpush": "아주 느리게 다가감 (강조 컷)",
                 "slowslide": "아주 느리게 옆으로 (여러 명·강조 컷)",
                 "crash": "돌진 줌", "whip": "휙 꺾기(휩팬)",
                 "handheld": "핸드헬드 추적", "riseorbit": "솟아오르며 공전",
                 "hyperlapse": "하이퍼랩스 돌진",
                 "fpv": "FPV 드론 슉슉", "dollyzoom": "돌리 줌(현기증)",
                 "whiptilt": "휙 틸트(상하)", "roll": "롤 회전",
                 "chase": "체이스캠 추격", "sweeparc": "휘돌아 아크 (좌→우 삥)",
                 "gamecam": "게임 3인칭 팔로우",
                 "needle": "틈 통과 (좁은 구멍→내부)", "bullettime": "불릿타임 (멈춘 채 공전)",
                 "whiproll": "휩 롤 (회전 블러 전환)"}
# 카메라 호버 설명 — 옵션이 많아져서 선택 시 마우스 올리면 뭘 하는 워크인지 보이게
CAMERA_DESCS = {
    "push": "피사체로 천천히 다가갑니다 — 집중·긴장감. 무난한 기본기",
    "pull": "뒤로 물러나며 주변이 드러납니다 — 전경 공개·반전용",
    "down": "화면이 아래로 훑고 내려갑니다 — 위→아래 구조 설명",
    "up": "화면이 위로 훑고 올라갑니다 — 규모·높이 강조",
    "panright": "카메라가 오른쪽으로 미끄러집니다 — 나열·이동",
    "panleft": "카메라가 왼쪽으로 미끄러집니다 — 나열·이동",
    "pushdown": "다가가면서 동시에 하강 — 드론이 내려꽂히는 훅 오프닝",
    "pullup": "물러나면서 상승(줌아웃+드론 상승) — 전경 공개·마무리에 최적",
    "orbit": "피사체를 중심에 두고 호를 그리며 돕니다 — 배경이 돌아 입체감. 빠르기는 '움직임' 설정을 따름",
    "still": "카메라 완전 고정 — 피사체 변화(모션)가 주인공일 때. 실험·도해 컷",
    "slowpush": "거의 안 느껴질 만큼 천천히 다가감 — 치수선·화살표가 붙은 컷용. 강조가 화면 밖으로 밀려나지 않으면서 정지화면처럼 보이지도 않습니다",
    "slowslide": "거의 안 느껴질 만큼 천천히 옆으로 미끄러집니다 — 인물이 셋 이상인 컷용. 크게 도는 오빗은 인원수·배치를 무너뜨리지만 이 정도 이동폭은 유지됩니다 (실측 2026-08-15)",
    "sweeparc": "피사체 고정 + 좌→우로 빠르게 삥 도는 아크 — 역동 회전",
    "needle": "좁은 틈·구멍·문틈을 뚫고 안으로 들어갑니다 — 통로·배관·단면 내부로 진입할 때. 벽이 양옆을 스치고 지나갑니다",
    "bullettime": "장면은 거의 멈춘 채 카메라만 빠르게 공전합니다 — 파편·물방울이 정지한 순간을 도는 훅 컷용",
    "whiproll": "화면이 빠르게 회전하며 뭉개졌다가 멈춥니다 — 장면 전환용. 블러가 강해 다음 장면으로 넘기기 좋습니다",
    "crash": "피사체로 확 꽂히는 급가속 줌 — 충격·강조 한 방",
    "whip": "화면이 옆으로 휙 꺾이며 도착 — 빠른 전환감",
    "whiptilt": "화면이 위/아래로 휙 꺾입니다 — 높이차 강조",
    "fpv": "레이싱 드론처럼 장면 사이를 슉슉 파고듭니다 — 가장 과격한 워크",
    "dollyzoom": "피사체는 그대로, 배경만 쭉 늘어나는 현기증 효과 — 훅 시선 강탈",
    "roll": "수평선이 기울며 회전 — 불안감·이상함 연출",
    "chase": "움직이는 피사체 뒤에 붙어 질주 — 추격감",
    "handheld": "들고 찍은 듯한 흔들림 — 현장감·긴박감",
    "riseorbit": "낮은 앵글에서 떠오르며 도는 복합 워크 — 웅장한 공개",
    "hyperlapse": "시간이 빨리 흐르며 공간을 질주 — 배속감",
    "gamecam": "캐릭터 뒤 몇 미터, 어깨 높이에서 걸음에 맞춰 따라가는 오픈월드 게임 카메라 — game 톤 인물 이동 컷의 기본",
}
# UI select optgroup 순서
CAMERA_GROUPS = [("줌", ["push", "pull"]),
                 ("이동", ["down", "up", "panright", "panleft", "gamecam"]),
                 ("복합", ["pushdown", "pullup", "orbit"]),
                 ("역동", ["sweeparc", "crash", "whip", "whiptilt", "fpv", "dollyzoom", "roll",
                          "chase", "handheld", "riseorbit", "hyperlapse",
                          "needle", "bullettime", "whiproll"]),
                 ("고정", ["still", "slowpush", "slowslide"])]
# 구버전 카메라 id → 대체 (기존 config·컷 데이터가 남아 있어도 깨지지 않게)
CAMERA_MIGRATE = {"aerial": "pullup"}

# 샷/컷타입 → 카메라 자동 매핑. 실측 분포를 따랐다:
# 아래로 이동 32~68%(최다) · 다가감 39~56% · 물러남 32~36% · 고정 4~25%(드묾)
CAMERA_AUTO_SHOT = {"cutaway": "down", "macro": "pushdown", "wide": "pullup",
                    "pov": "push", "object": "orbit", "screen": "push",
                    "close": "pushdown"}
CAMERA_AUTO_TYPE = {"context": "pullup", "analogy": "panright", "reaction": "push"}
# 대본 비트가 있으면 샷보다 우선한다 — 마무리는 물러나며, 해법은 파고들며
CAMERA_AUTO_BEAT = {"closing": "pullup", "solution": "pushdown", "pivot": "push"}
# ⛓ 체인 컷이 자동 카메라일 때 앞 클립과 같은 워크면 방향을 꺾는다 — 롱테이크가 단조로워지지 않게
CHAIN_TURN = {"push": "riseorbit", "pushdown": "orbit", "pull": "panright", "pullup": "orbit",
              "down": "panright", "up": "orbit", "panright": "pushdown", "panleft": "pushdown",
              "orbit": "pullup", "riseorbit": "push", "crash": "orbit", "whip": "push",
              "handheld": "orbit", "hyperlapse": "orbit", "still": "push",
              "fpv": "orbit", "dollyzoom": "pullup", "whiptilt": "push",
              "roll": "push", "chase": "orbit", "sweeparc": "push"}


def norm_camera(c, default="push"):
    c = CAMERA_MIGRATE.get(c, c)
    return c if c in CAMERA_PRESETS else default


# Veo 는 오디오를 끌 수 없고(Always on), 지시가 없으면 아무 소리나 만든다 — 말소리가 섞이면
# 편집에서 나레이션과 충돌한다. 조용한 룸톤만 요청해 깨끗한 소재로 만든다.
# 움직임 세기. 쇼츠는 첫 1초 이탈 싸움이라 '역동'이 기본값 — 화면에서 항상 뭔가 크게 변해야
# 시선이 갇힌다. '차분'은 레퍼런스 채널 원래 템포(느리고 의도적)를 원할 때.
VIDEO_TEMPO = {
    # 이어짐 컷용 — 힘은 있되 흔들지 않는다. 격한 리프레임은 다음 클립과의 이음매를
    # 어긋나게 하고, 도착 프레임에 정확히 안착하지 못하게 한다 (Flow 자문 2026-08-12).
    "smooth": ("The movement is confident and continuous, carried by one steady sweep — "
               "the camera never stops, but it also never jerks: no sudden reframes, no speed "
               "changes, no handheld shake. It arrives settled, not still mid-swing."),
    "dynamic": ("The movement is fast, bold and energetic with a clear sense of momentum — "
                "the camera keeps advancing and the motion in the scene is vivid and continuous. "
                "Every single second of the clip brings a new visible change; the frame never "
                "rests or settles, not even for a moment. Quick reframes, speed changes and "
                "handheld energy are welcome as long as the subject stays readable."),
    "calm": ("The camera move and the motion are slow and deliberate — this is an explainer shot, "
             "not an action shot. Keep the composition stable enough to read."),
    # 배속·타임랩스 — 실제 배속이 아니라 '배속으로 찍은 것 같은' 영상을 생성한다.
    # 진짜 배속이 필요하면 편집에서 자르는 게 확실하다 (4초 클립을 2배속 → 2초).
    "hyper": ("The footage looks like sped-up, time-lapse style motion — actions unfold several "
              "times faster than real time, light and movement streak and flow, everything is "
              "compressed and rapid as if shot in hyperlapse. The subject stays readable."),
}
# Veo 는 오디오를 끌 수 없다(Always on) → 어떤 소리를 만들지 명시해야 한다.
# room: 나레이션을 얹는 컷용(조용한 룸톤만) / sfx: 장면 효과음만(물소리·기계음 등) — 둘 다 대사·음악 금지
VIDEO_AUDIO_MODES = {
    "room": ("Ambient noise: only a quiet, natural room tone or subtle environmental hum "
             "that fits the scene. No dialogue, no speech, no voice-over, no music."),
    "sfx": ("Sound design: vivid, natural diegetic sound effects that match the scene and its "
            "actions — flowing water, sizzling, cracking, wind, mechanical hums, impacts — "
            "clearly audible and synced to the motion. "
            "No dialogue, no speech, no voice-over, no music, no crowd chatter."),
}
VIDEO_AUDIO = VIDEO_AUDIO_MODES["room"]   # 하위 호환 기본값

# ── 모션 프리셋 — '무엇이 어떻게 변하는가'의 표현 어휘 (모션 칸에 채워 넣는다) ──
# 레퍼런스 채널 역추적 결과, 정지컷과 영상컷을 가르는 건 카메라가 아니라 이 변화의 종류였다.
MOTION_PRESETS = [
    ("조립·변형", [
        ("assemble", "자가조립 — 부품이 날아와 스스로 조립됨",
         "the separate pieces fly in from off-frame one after another and assemble themselves "
         "into the finished structure, locking into place"),
        ("disassemble", "역조립 — 부품이 떨어져 나가 흩어짐",
         "the structure comes apart piece by piece, the parts drifting away from each other"),
        ("exploded", "분해도 — 부품이 공중에 펼쳐짐",
         "the object separates into an exploded technical view, each part floating apart in mid-air "
         "while staying aligned on its axis"),
        ("morph", "모핑 — 다른 형태로 변형됨",
         "the shape smoothly transforms into a completely different form, every surface flowing "
         "into its new geometry"),
        ("grow", "성장 — 자라나며 커짐",
         "the form grows and extends outward, new material emerging and taking shape as it rises"),
    ]),
    ("파괴·풍화", [
        ("collapse", "붕괴 — 무너져 내림",
         "the structure gives way and collapses, pieces tumbling down in a heavy cascade"),
        ("crack", "균열 — 금이 가며 갈라짐",
         "a crack opens and races across the surface, splitting it apart with fragments breaking loose"),
        ("erode", "침식 — 깎여 나감",
         "the surface is worn away layer by layer, material stripping off and washing out of frame"),
        ("burn", "화재 — 불길이 번짐",
         "flames catch and spread rapidly across the structure, wood blackening and smoke pouring upward"),
        ("age", "세월 — 낡아감",
         "decades pass in seconds: the surface weathers, discolours, cracks and grows over"),
    ]),
    ("유체·물성", [
        ("flood", "차오름 — 물이 차오름",
         "water rises and floods into the space, the level climbing steadily up the frame"),
        ("seep", "스며듦 — 층을 통과해 스밈",
         "liquid seeps down through the layers, soaking through and finding paths between the particles"),
        ("pour", "쏟아짐 — 부어지고 넘침",
         "a heavy stream pours in and spills over, splashing and spreading across the surface"),
        ("cure", "응고 — 굳어 단단해짐",
         "the liquid thickens and sets hard, turning matte and locking everything it touches together"),
        ("dissolve", "용해 — 풀어져 사라짐",
         "the material softens, breaks apart and dissolves away into the surrounding liquid"),
        ("crystal", "결정 — 결정이 자람",
         "sharp crystals nucleate and grow outward across the surface in a spreading bloom"),
    ]),
    ("시각화", [
        ("cutaway", "단면 절개 — 잘려 속이 드러남",
         "the near half of the object slides away to reveal a clean cross-section of the inside"),
        ("xray", "투시 — 내부가 비쳐 보임",
         "the outer shell turns translucent and the internal structure lights up inside it"),
        ("flow", "흐름 — 발광선이 경로를 따라 흐름",
         "glowing lines trace the path of force through the structure, pulses travelling along them"),
        ("heat", "열 전파 — 열이 번짐",
         "heat spreads through the material, the glow creeping outward from the source"),
        ("timelapse", "타임랩스 — 시간이 빠르게 흐름",
         "time races forward: light sweeps across the scene and everything changes in fast motion"),
        ("holo", "홀로 점등 — 이미지 속 홀로그램이 켜져 살아남 (홀로 컷 전용)",
         "the translucent cyan hologram already standing in the frame powers up to full "
         "presence: its wireframe edges brighten and trace themselves, slow scan lines "
         "shimmer across its see-through surfaces, and it settles into a steady, gently "
         "pulsing glow — while the real scene around it stays still and photoreal"),
        ("hud", "그래픽 HUD — 글자 없는 도형이 그려짐 (주석과 함께 쓰지 말 것)",
         "a hairline cyan HUD graphic draws itself into the scene — an arc gauge filling "
         "steadily, slim bars rising side by side, or a fine survey grid unfolding cell by "
         "cell, ONE device only — pure glowing geometry with no letters or digits, "
         "everything else unchanged"),
    ]),
]
MOTION_PRESET_MAP = {k: en for _, items in MOTION_PRESETS for k, _, en in items}


def is_holo_cut(cut):
    """홀로그램 재구성 컷 판별. 분해 지시문 [3-1]의 표준 문구가 'hologram' 단어를 반드시
    포함하므로 키워드 매칭이 신뢰 가능하다 — 주석 강제 공백·검수 경고·유지 절 첨부가
    전부 이 판별 하나를 같이 쓴다 (판별 기준이 갈라지면 게이팅에 구멍이 난다)."""
    return "hologram" in ((cut.get("subject_en") or "") + " " +
                          (cut.get("motion") or cut.get("motion_en") or "")).lower()


def is_exploded_cut(cut):
    """분해뷰 컷 판별. 홀로그램(is_holo_cut)과 같은 방식 — 전용 필드를 두지 않고
    분해 지시문 [5-2]가 강제하는 표준 문구 'exploded view'를 키워드로 잡는다.
    (필드를 새로 만들면 분해기·UI·드래프트 저장·프롬프트 4곳이 동시에 맞아야 해서
     어긋날 여지가 커진다 — 홀로그램에서 이미 검증된 방식을 그대로 쓴다)
    주석 강제 공백과 영상 유지 절 첨부가 이 판별 하나를 같이 쓴다."""
    return "exploded view" in ((cut.get("subject_en") or "") + " " +
                               (cut.get("motion") or cut.get("motion_en") or "")).lower()


def is_graphic_cut(cut):
    """글자 없는 그래픽 컷 판별 — 지침 [4]가 강제하는 고정 문구를 키워드로 잡는다
    (홀로그램·분해뷰와 같은 방식). 그래픽을 subject_en 에 굽는 2단 구조로 바꾸면서
    strip_graphic_motion 의 자동 게이팅 밖으로 나갔다 — 그 자리를 이 판별이 메운다.
    도형 자체가 강조 장치라, 그 위에 주석까지 얹히면 화면이 계기판이 된다."""
    return "flat cyan graphic overlay" in (cut.get("subject_en") or "").lower()

# 영상 주석 — 레퍼런스 채널의 핵심. 주석이 '그려지며 나타나고 흘러가는' 것이 시선을 잡는다.
# animate: 시작 프레임에 이미 주석이 있을 때 그것을 살아 움직이게
# draw   : 깨끗한 시작 프레임에 주석을 새로 그려 넣게 (이미지에 주석이 없을 때)
VIDEO_ANNO_MODES = {
    # ⚠ 'traces along' 은 모델이 **선이 물체 위를 훑고 지나간다**로 읽는다 — 실제로 HUD 막대가
    # 제품 위를 미끄러지는 클립이 나왔다 (2026-08-11 제보). 위치는 못으로 박고, 움직이는 것은
    # '선 안을 지나가는 빛'뿐이라고 못박는다. 정지만 시키면 죽은 화면이 되므로 액션은 남긴다.
    # 2026-08-12 수정 — 이 판만 '지웠다 다시 그려라'로 쓰여 있었다 (주석·다른 판 전부와 반대).
    # 실측: 트로이 편에서 이 문구가 들어간 컷 2개 전부가 VIDEO_TEXT_KEEP('그 글자는 절대
    # 지우지 마라')과 한 프롬프트에서 충돌했다 — 치수선을 지우라면서 치수선 위 글자는 지키라는 말.
    # 게다가 2K 에 구운 헤어라인을 720p 에서 재작도하게 만들어 대표 실패 모드를 자초했다.
    # → 다른 *_animate 와 같은 문법으로: 위치는 못으로 박고 '선 안을 지나가는 빛'만 움직인다.
    #   채널 시그니처인 '그려지는 느낌'은 눈금이 빛을 따라 차례로 켜지는 것으로 살린다.
    "animate": ("The {accent} HUD is already drawn in the provided frame and stays exactly as it "
                "is — same position, same size, same shape. Keep every existing stroke crisp and "
                "unchanged: never erase it, never blur it, never redraw it, never restart it from "
                "nothing. It never slides across the object, never drifts in from off-screen, "
                "never sweeps over the subject as a whole bar, and never changes position or size "
                "— that last part is the failure to avoid. Only the camera moves. "
                "The only animation is a brighter pulse of light running once along the hairline "
                "from one end to the other, the fine graduation ticks lighting up one after "
                "another as it passes; once it reaches the end the whole HUD settles into a "
                "steady glow and holds. "
                "Any circular ground grid already drawn simply holds its place — never add new "
                "grid elements. "
                "It happens once: no looping, no blinking, no repeated scanning, no fading out. "
                "All of it reads one thing: {focus} "
                "It stays locked in perspective to what it measures as the shot moves. "
                # 영상은 720p 로 나간다 — 1080p 기준 1~2px 을 요구하면 실효 1px 미만이 되어
                # 렌더 중에 선이 사라진다 (2026-08-12 실측: 6초 클립에서 치수선이 축소돼 소멸).
                # 절대 픽셀 대신 '축소 후에도 남는 굵기'로 지시한다.
                "Clean thin strokes — fine enough to look like an instrument reading, but still "
                "solid and unbroken after the clip is scaled down to a phone screen. "
                "They hug exactly the thing named above — not the biggest or most prominent "
                "object in the frame — rather than stretching across empty ground. "
                "The HUD is bare geometry: no viewfinder box floating in mid-frame, no corner "
                "brackets, no icons, no scanner readouts, no serial codes or interface labels — "
                "no letters, digits or words."),
    # 지면 원형 그리드는 '땅에 선 구조물을 측량하는 와이드 컷'에서만 — 이미지 쪽 규칙과 같다
    # (2026-08-11: 이미지만 wide 한정으로 고치고 영상은 무조건이라, 클로즈업·소품 클립마다
    #  화면 아래에 대형 레이더 원판이 그려져 피사체에서 시선이 이탈했다)
    "draw": ("Early in the shot a {accent} holographic technical HUD switches on over the scene, "
             "reading exactly one thing: {focus} A single hairline contour draws itself onto the "
             "outline of that one thing{dim}{grid}, with a soft neon bloom — the line grows from "
             "one end of that outline to the other and stops there. "
             "It finishes drawing within the first second or two and then holds: the finished "
             "line stays exactly on that outline and never slides across the object, never "
             "drifts, never sweeps over it again. No looping, no blinking, no redrawing, no "
             "fading out. "
             "It stays locked to what it measures. Rendered by software, never hand-drawn: "
             # 720p 출력 — 절대 픽셀 대신 축소 후에도 남는 굵기로 (위 animate 와 같은 이유)
             "clean thin strokes, fine but still solid and unbroken after the clip is scaled "
             "down to a phone screen, hugging exactly the thing named above — not the biggest "
             "or most prominent object in the frame — rather than stretching across empty ground. "
             "The HUD is bare geometry: no viewfinder box floating in mid-frame, no corner "
             "brackets, no icons, no scanner readouts, no serial codes or interface labels — "
             "no letters, digits or words."),
    # 발광 하이라이트 판 — HUD(선) 대신 대상 전체를 반투명 발광으로 점등 (피라미드 룩)
    "glow_animate": ("The translucent {accent} glow overlay already covering the structure holds "
                     "steady and simply breathes: a very slow, barely-there shift of light across "
                     "its surface, with the edges and ridgelines staying evenly lit. It never "
                     "flashes, strobes, loops or fades out. It highlights exactly one thing: {focus} "
                     "That is what glows — not the biggest or most prominent object in the frame. "
                     "It stays locked to the structure's surface in perspective as the shot "
                     "moves, never spilling onto the ground or sky. The rest of the frame stays "
                     "natural. Pure light only — no letters, digits, words or interface "
                     "elements."),
    # ── extent·outline 판 (2026-08-18 신설) — 이 둘만 판이 없어서 영상 프롬프트에
    #    유지·잠금 절이 통째로 빠졌었다 (구운 그래픽을 지키라는 지시 부재 = 소실 금지의 구멍).
    "extent_animate": ("The {accent} light already running along the full length of the subject "
                       "stays exactly where it is, hugging the same line from end to end, locked "
                       "to it in perspective as the shot moves. It marks how far one thing "
                       "reaches: {focus} "
                       "Its full length is visible in every frame — it never grows, shortens or "
                       "gets drawn in progressively. The only animation is a single brighter "
                       "pulse travelling once along it from one end to the other, after which "
                       "the whole length settles to a steady glow and holds. It never blinks, "
                       "loops or fades out. No new lines, no letters, digits or words."),
    "outline_animate": ("The thin {accent} outline already tracing one thing stays exactly on "
                        "its silhouette — same shape, same thickness, locked to it in "
                        "perspective as the shot moves. It singles out: {focus} "
                        "The complete outline is visible in every frame — it never redraws, "
                        "breaks, drifts off the edge, multiplies or fades out. The only "
                        "animation is a single brighter pulse travelling once around the "
                        "outline, after which it settles to a steady glow and holds. Nothing "
                        "else in the frame is marked. No letters, digits or words."),
    # ── 화살표·X·영역 판 (레퍼런스 실측으로 추가) ──────────────────────
    # 공통: 라벨(글자)은 여기서 그리지 않는다. 2K 이미지에 구운 것을 I2V 가 유지할 뿐이다
    # (720p 6초에서 새 글자를 그리게 하면 뭉개진다 — VIDEO_TEXT_KEEP 과 같은 원리).
    "arrow_draw": ("Early in the shot a single bold {accent} arrow draws itself into the scene, "
                   "showing exactly one movement: {focus} The arrow grows from its tail to its "
                   "head along the real path in perspective, reaching full length within the "
                   "first second or so, and then holds. "
                   "Only ONE arrow — never a scatter of arrows, never repeated chevrons, never "
                   "a new arrow appearing later. Once drawn it stays put: it does not slide "
                   "around the frame, loop, blink or fade out. No letters, digits or words."),
    # ⚠ 길이 고정을 따로 못박는다. '펄스가 꼬리→머리로 지나간다'만 쓰면 모델이 그걸
    #   **화살표가 자라거나 줄어드는 것**으로 읽는다 (2026-08-16 실측: 4초 클립에서
    #   꼬리가 프레임마다 후퇴해 화살표가 계속 짧아졌다). 밝기만 변한다고 분리해서 적는다.
    "arrow_animate": ("The existing {accent} arrow is locked to the scene in perspective: same "
                      "position, same size, same angle. Zero drift, zero duplication, zero "
                      "morphing. It shows one movement: {focus} "
                      "Its full length is visible in every single frame from the first to the "
                      "last: the tail and the head both stay pinned exactly where they are, and "
                      "the arrow never grows, shortens, retracts, extends or gets drawn in "
                      "progressively. The only animation is a travelling highlight — a brighter "
                      "band of light sliding once along the arrow from tail to head while the "
                      "arrow's own shape stays completely unchanged — after which it settles to "
                      "a steady glow and holds. No looping, no blinking, no fading, no new arrows."),
    "reject_draw": ("Early in the shot a single large {accent} X is stamped over exactly one "
                    "thing: {focus} The two strokes snap in quickly, one after the other, and "
                    "then the X holds perfectly still for the rest of the clip. "
                    "Just the one X — nothing else is marked, no extra symbols appear, and it "
                    "never slides, spins, blinks or fades out. No letters, digits or words."),
    "reject_animate": ("The large {accent} X already in the frame stays exactly where it is, "
                       "covering the same thing at the same size and angle: {focus} "
                       "It holds steady with only a faint settle of light along its strokes — "
                       "it never slides, spins, multiplies, blinks or fades out."),
    "zone_draw": ("Early in the shot a {accent} outline draws itself around exactly one "
                  "region: {focus} The boundary traces around that region until it closes, and "
                  "the area inside fills with a clearly visible translucent tint of the same "
                  "colour, everything beneath it staying recognisable through it. This finishes "
                  "within the first second or so and then holds. "
                  "One region only. Once closed the outline stays locked to that region in "
                  "perspective as the shot moves — it never slides across the scene, never "
                  "resizes, never blinks or fades out. No letters, digits or words."),
    "zone_animate": ("The {accent} boundary already drawn around one region stays locked "
                     "to it: same shape, same size, same place. It encloses one thing: {focus} "
                     "A brighter pulse travels once around the boundary and then it settles into "
                     "a steady glow. It never slides, resizes, multiplies, blinks or fades out."),
    # 만화 기호 판 — anime 톤. 홀로그램·발광 대신 집중선·충격 기호가 '탁' 하고 붙는다.
    # 만화는 원래 정지 기호라, 계속 흐르게 하면 그림이 지저분해진다 → 붙고 나면 멈춘다.
    "manga_draw": ("Early in the shot, cartoon emphasis marks snap into place around exactly one "
                   "thing: {focus} Thick focus lines sweep inward toward it from the edges of the "
                   "frame and a few bold flat impact marks pop in beside it. They land within the "
                   "first second or two and then hold perfectly still for the rest of the clip: "
                   "no looping, no blinking, no drifting, no fading out. They are drawn in the "
                   "same thick dark outline and flat color as the picture — flat shapes only, "
                   "never glowing, never translucent. No letters, digits or words."),
    "manga_animate": ("The cartoon emphasis marks already in the frame hold their place and only "
                      "quiver very slightly, the way a held manga panel does. They keep pointing "
                      "at exactly one thing: {focus} They never multiply, drift, blink or fade "
                      "out, and no new marks are added. Flat shapes in the same outline and color "
                      "as the picture — never glowing. No letters, digits or words."),
    "glow_draw": ("As the shot plays, a translucent {accent} holographic overlay ignites over "
                  "exactly one thing: {focus} That is what lights up — not the biggest or most "
                  "prominent object in the frame. The glow sweeps up from its base to its top as it "
                  "switches on, filling the structure's entire visible volume with soft luminous "
                  "energy — noticeably brighter along its edges, ridgelines and silhouette, with "
                  "a small bright flare at its highest point. The overlay clings exactly to the "
                  "structure's surface and stays locked to it in perspective as the shot moves, "
                  "never spilling onto the ground, sky or neighbouring objects. Everything else "
                  "in the frame stays untouched and natural. Pure light only — no letters, "
                  "digits, words or interface elements."),
    # ── 흐름 판 (2026-08-12 추가) ────────────────────────────────────────
    # arrow 는 '어디로 가는가'(방향 하나)를, flow 는 '어디서 나와 무엇을 지나 어디로 끝나는가'
    # (출발-경로-상호작용-도착)를 그린다. 힘·하중·물·공기·열·전기처럼 눈에 안 보이는 흐름 전용.
    # 핵심 설계: 경로 자체는 2K 이미지에 **굵은 띠**로 굽고, 영상은 그 위를 지나가는 밝은 앞머리
    # 하나만 움직인다. 가는 선을 영상이 새로 그리면 720p 에서 뭉개진다(헤어라인 실측과 같은 계열).
    "flow_draw": ("Early in the shot one broad {accent} flow band draws itself into the scene along "
                  "the real structure, showing exactly one continuous flow: {focus} It is a broad translucent "
                  "ribbon of glowing light — soft edges, brighter core — never an opaque painted "
                  "object, never a cartoon arrow with a big triangular arrowhead. The band grows "
                  "from where the flow starts, follows the actual physical route, and stops where "
                  "the flow ends, reaching full length within the first second or so. "
                  "Then a single brighter front travels once along it from the source to the "
                  "outlet, after which the whole band settles into a steady glow and holds. "
                  "It is ONE broad continuous band — never a hairline, never a bundle of thin "
                  "streamlines, never repeated arrows or chevrons, never branching into side "
                  "paths, never a second flow. Once drawn it stays locked to the structure in "
                  "perspective as the shot moves: it never slides across the scene, never "
                  "redraws, never loops, blinks or fades out. No letters, digits or words."),
    # ── 빈 공간 판 ──────────────────────────────────────────────
    # 채워진 부피는 '숨쉬듯' 아주 느린 밝기 변화만 준다. 크기·경계를 움직이면 방이 자라나
    # 보여서 공간을 잘못 읽는다 (glow_animate 와 같은 원리).
    "void_draw": ("Early in the shot a translucent {accent} volume fills exactly one empty space, "
                  "flooding it from wall to wall so the shape of the hollow itself becomes "
                  "visible: {focus} It fills up smoothly within the first second or so and then "
                  "holds. It stops at the real surfaces enclosing it and never leaks through them; "
                  "the material around it stays completely opaque — the walls never turn "
                  "transparent. Once filled it never grows, shrinks, drifts, pulses, blinks or "
                  "fades out. No letters, digits or words."),
    "void_animate": ("The translucent {accent} volume already filling the empty space holds its "
                     "exact shape and size — the boundary never grows, shrinks or drifts, because "
                     "that boundary is the shape of the space being explained: {focus} "
                     "The only animation is a very slow, barely-there breath of light through it, "
                     "the edges where it meets the surrounding material staying evenly lit. "
                     "It stays locked in place in perspective as the shot moves, never leaks into "
                     "the surrounding material, and never flashes, loops or fades out. The walls "
                     "around it stay fully opaque. No letters, digits or words."),
    # ── 동선 판 ────────────────────────────────────────────────
    "route_draw": ("Early in the shot a single {accent} route line draws itself through the space, "
                   "tracing exactly one path that people or objects took: {focus} It grows from "
                   "the start point along the floor and through the openings in perspective, "
                   "turning where the passage turns, and stops at the end point — reaching full "
                   "length within the first second or two, then holding. "
                   "Only ONE route: never a network, never branching alternatives, never repeated "
                   "arrows along it, and it never cuts through solid walls. Once drawn it stays "
                   "locked to the floor in perspective — it never slides, redraws, loops, blinks "
                   "or fades out. No letters, digits or words."),
    "route_animate": ("The {accent} route line already drawn through the space stays exactly where "
                      "it is, locked to the floor in perspective as the shot moves. It traces one "
                      "path: {focus} " 
                      "The line's full length is visible in every frame — it never grows, shortens or gets drawn in progressively. "
                      "The only animation is a single brighter point of light "
                      "travelling once along it from the start marker to the end marker, after "
                      "which the whole line settles into a steady glow and holds. "
                      "The line never moves, redraws, branches or multiplies, and no arrows are "
                      "added. No letters, digits or words."),
    # ── 신규 7종 (2026-08-12) — 전부 '이미 있는 것을 유지하고 하나만 움직인다' 골격.
    #    시작 이미지에 구워진 그래픽이라 영상은 새로 그리지 않는다.
    "gauge_animate": ("The {accent} gauge bar already visible in the frame stays exactly where it "
                      "is — same position, same scale, same tick marks, locked in place as the "
                      "shot moves. It reads one quantity: {focus} The only animation is the fill "
                      "rising once from the bottom of the track up to its final level, taking "
                      "about a second, then holding there for the rest of the clip. The reading "
                      "beside it stays exactly as it is — never recounting, never changing value. "
                      "No second gauge, no looping, no blinking, no new text."),
    "gauge_draw": ("Early in the shot the {accent} gauge bar rises into view beside the subject "
                   "and its fill climbs once from empty to the level that represents: {focus} "
                   "It reaches that level within the first second or so and then holds, "
                   "completely still, for the rest of the clip. Only ONE gauge. "
                   "No looping, no blinking, no fading out, and no new text."),
    "scale_animate": ("The white outlined objects standing beside the subject for scale stay "
                      "exactly where they are — same size, same position, same ground plane, "
                      "locked in perspective as the shot moves. They show: {focus} "
                      "They never walk, drive, rotate, multiply or fade. The only permitted "
                      "animation is a single soft brightening of their outlines that passes once "
                      "and settles. The subject itself is never covered by them."),
    # 분할 비교 — 다른 도구는 그래픽만 지키면 되지만 이건 레이아웃 자체를 지켜야 한다.
    # 두 면이 각자 살아 있되 경계선은 절대 안 움직인다. 카메라는 _auto_camera 가 still 로
    # 묶으므로 여기서는 화면 구성만 못박는다.
    "versus_animate": ("The frame stays split into the two stacked panels exactly as it is — the "
                       "boundary between them does not move, tilt, sweep or wipe, no line or bar "
                       "appears there, and neither panel grows, shrinks or slides. "
                       "The comparison being shown is: {focus} "
                       "Inside each panel only light, dust, haze or water moves, gently and "
                       "independently, so both halves are alive without either one changing what "
                       "it shows. Nothing ever crosses the boundary, the two panels never "
                       "merge into a single view, and no wipe or transition happens between them."),
    "versus_draw": ("The frame stays split into the two stacked panels exactly as it is — the "
                    "boundary between them does not move, tilt, sweep or wipe, no line or bar "
                    "appears there, and neither panel grows, shrinks or slides. "
                    "The comparison being shown is: {focus} "
                    "Inside each panel only light, dust, haze or water moves, gently and "
                    "independently. Nothing crosses the boundary and the two panels never "
                    "merge into a single view."),
    "spin_animate": ("The {accent} helical rotation sweep already drawn around the part stays "
                     "exactly where it is, locked to the part in perspective — same turns, same "
                     "radius, never unwinding, tightening or multiplying. It marks: {focus} "
                     "The only animation is a single point of brighter light travelling once "
                     "along the sweep in the direction of rotation, after which it settles to a "
                     "steady glow. No new rings, no text."),
    "wave_animate": ("The {accent} wavefront rings already drawn in the frame stay exactly where "
                     "they are, locked to the scene in perspective — same radii, same spacing, "
                     "never expanding, shrinking or multiplying. They mark: {focus} The only "
                     "animation is a single pulse of brightness passing once from the innermost "
                     "ring outward, after which all rings settle to a steady glow. No new rings, "
                     "no text."),
    "skeleton_animate": ("The {accent} internal network already drawn on the subject stays exactly "
                         "where it is, every member locked to the subject in perspective as it "
                         "moves — never redrawn, never spreading further. It reveals: {focus} "
                         "The network's full extent is visible in every frame. The only animation "
                         "is a single wave of brightness travelling once through the network from "
                         "its origin outward, then settling to a steady glow. No new lines, no text."),
    "loadsplit_animate": ("The {accent} force path already drawn on the structure stays exactly "
                          "where it is, locked in perspective — the stream, the split and both "
                          "branches all pinned, full length visible in every frame, never growing "
                          "or shortening. It shows: {focus} The only animation is a single pulse "
                          "of brightness entering at the top, dividing at the split and running "
                          "down both branches at once, then the whole path settles to a steady "
                          "glow. The avoided region stays completely clean. No new lines, no text."),
    "trajectory_animate": ("The {accent} flight arc already drawn through the air stays exactly "
                           "where it is, locked to the scene in perspective — its full curve from "
                           "launch to impact visible in every frame, never growing, shortening or "
                           "getting drawn in progressively. It traces: {focus} The only animation "
                           "is a single point of brighter light travelling once along the arc from "
                           "launch to impact, after which the arc settles to a steady glow. "
                           "No second arc, no text."),
    "graph_animate": ("The {accent} analytic curve already drawn on the structure stays exactly "
                      "where it is, locked in perspective as the shot moves — axis, ticks, curve "
                      "and wash all pinned, never redrawn, never shifting. It shows: {focus} "
                      "The curve's full length is visible in every frame — it never grows, "
                      "shortens or gets drawn in progressively. The only animation is a single "
                      "point of brighter light travelling once along the curve from the smallest "
                      "value to the greatest, after which the whole graph settles to a steady "
                      "glow and holds. No new lines, no text."),
    "marker_animate": ("The small {accent} dots already visible in the frame stay exactly where "
                       "they are, each locked to its own point on the surface in perspective as "
                       "the shot moves. They mark: {focus} The only animation is one soft pulse "
                       "of brightness that passes across the whole set once — all dots together, "
                       "not one after another — and then settles to a steady glow. "
                       "No new dots appear, none disappear, none drift, and no lines join them."),
    "count_animate": ("The {accent} dots and the running total already visible in the frame stay "
                      "exactly where they are, locked in perspective as the shot moves. "
                      "They mark: {focus} The only animation is one soft pulse across all the "
                      "dots together, after which everything holds. The total never recounts, "
                      "never ticks up, never changes — it stays exactly the value already shown. "
                      "No new dots, no new text."),
    "crack_animate": ("The {accent} line tracing the crack stays exactly on the fracture, locked "
                      "to the surface in perspective as the shot moves. It traces: {focus} "
                      "The line's full length is visible in every frame — it never grows, shortens or gets drawn in progressively. "
                      "The only animation is a single glow travelling once along the crack from "
                      "one end to the other, after which the line returns to a steady state and "
                      "holds. The crack itself never widens, spreads, branches further or "
                      "repairs, and the stone around it never moves. No new lines, no text."),
    "bracket_animate": ("The four {accent} corner brackets already in the frame stay exactly "
                        "where they are, framing the same area at the same size, tracking that "
                        "area as the shot moves so it stays inside them. They frame: {focus} "
                        "The only animation is one brief tightening — the corners draw in "
                        "slightly and settle — which happens once at the start. "
                        "They never close into a full rectangle, never rotate, never multiply, "
                        "and nothing inside them is covered."),
    "spotlight_animate": ("The pool of light picking out one thing stays exactly where it is, "
                          "following that thing in perspective as the shot moves so it never "
                          "slips off. It lights: {focus} Everything outside the pool stays "
                          "dimmed and desaturated for the whole clip — never brightening back, "
                          "never going black. The only animation is one gentle swell of the "
                          "light that rises and settles. No second pool appears, and the dimmed "
                          "surroundings never take over the frame."),
    "flow_animate": ("The broad {accent} flow band already visible in the frame stays exactly where "
                     "it is, locked to the structure in perspective as the shot moves — the band "
                     "itself never slides, redraws, branches, multiplies, loops, blinks or fades "
                     "out. It shows one continuous flow: {focus} "
                     "The band's full length is visible in every frame — it never grows, shortens or gets drawn in progressively. "
                     "The only animation is a single brighter front travelling once along the band "
                     "from the source, through the point where it acts on the structure, to the "
                     "outlet; it briefly intensifies at that interaction point. After the front "
                     "reaches the outlet the whole band returns to a steady glow and holds. "
                     "No second pulse, no new bands, no arrows or chevrons, and no letters, "
                     "digits or words."),
}


def video_anno_line(mode, cut, color="auto"):
    """영상 주석 문구. 가리킬 대상이 없으면 주석을 넣지 않는다 (맥락 없는 장식 방지).

    **영상에는 수치를 절대 새기지 않는다.** 720p·6초 클립에서 작은 글자를 요구하면
    모델이 뭉갠다 (실측 2026-08-06: "20km" → "2?:00"). 숫자는 2K 이미지의 주석이나
    편집 단계 자막으로 얹는다 — measure_en 은 그 편집 지시로만 남는다.
    """
    # 컷 성격에 맞는 판을 고른다 — 화살표·X·영역·발광·만화 기호. 나머지(hud)는 그대로.
    if mode in ("draw", "animate"):
        kind = anno_kind_for_cut(cut)
        if kind != "measure":
            mode = kind + "_" + mode
    tpl = VIDEO_ANNO_MODES.get(mode)
    focus = (cut.get("focus_en") or "").strip()
    if not tpl or not focus:
        return ""
    focus = focus.rstrip(" .;,") + "."      # 뒷문장과 붙지 않게 (annotation_block 과 같은 처리)
    # 지면 그리드 제거 (2026-08-12) — 이미지 쪽과 같은 이유다. 조건이 shot=="wide" 뿐이라
    # 실내·단면 와이드에도 바닥 원판이 깔렸고 설명이 아니라 장식으로 읽혔다.
    grid = ""
    # 치수선도 수치가 있는 컷에만 (이미지의 annotation_block 과 같은 원칙 — 컷당 강조 하나).
    # 영상에 수치를 '새기지는' 않지만, 치수선이 있어야 편집에서 그 위에 자막을 얹을 수 있다.
    # 치수선은 2K 이미지에 이미 그려져 있다 — 영상이 가는 선을 '자가 작도'하면 720p 에서
    # 뭉갠다([5-3] 금지 항목). 이미 있는 선의 밝기만 바꾸게 한다.
    dim = (", and the slim dimension line already visible beside it brightens once and holds"
           if (cut.get("measure_en") or "").strip() else "")
    return tpl.format(accent=anno_accent(color, cut), focus=focus, dim=dim, grid=grid)
# 카메라 워크 제한(whip pan·rapid zoom·shaky 금지)은 풀었다 — 역동 프리셋과 모순이라서.
# 클립 중간 편집 컷만 계속 막는다: 소재는 끊김 없는 원테이크여야 편집에서 자를 수 있다.
# 'HUD readouts' 전면 금지는 글자 없는 도형 HUD(게이지·스캔선·바)까지 지운다 — Motion 이
# 도형을 그리라는데 네거티브가 readouts 를 금지하면 반쪽 게이지가 나온다 (정면충돌).
# → '글자 읽어내기(alphanumeric readouts)'만 금지로 좁히고, 시키지 않은 HUD 장식은
#   별도 줄로 계속 막는다 (주석 없는 컷은 깨끗하게 — 채널 문법 유지).
VIDEO_NEGATIVE = ("Avoid: any text, letters, numbers, captions, subtitles, watermarks, logos. "
                  "Avoid: alphanumeric readouts, serial codes, interface labels, icons, corner "
                  "brackets. Avoid: HUD graphics, gauges or grids that the Motion above did not "
                  "explicitly ask for; when it does ask, they stay bare geometry with nothing "
                  "written on them. "
                  "Avoid: editing cuts or scene changes mid-clip — one continuous shot. "
                  "Avoid: people talking or mouthing words.")
# 시작 이미지에 수치가 구워져 있을 때 (2026-08-10 방침 전환: 지우지 말고 살린다).
# '영상이 새 글자를 그리는 것'은 계속 금지 — 720p에서 뭉개진다("20km"→"2?:00" 실측).
# 2K 이미지에 이미 선명하게 박힌 readout 을 I2V 가 유지하는 건 다른 문제라 지키게 한다.
# (전면 금지를 그대로 두면 모델이 이미지의 숫자를 지우거나 뭉개는 쪽으로 움직인다)
# 압축판 (2026-08-12) — 같은 제어 강도를 절반 길이로. 프롬프트가 길수록 뒤쪽 지시가
# 묻힌다는 지적을 받아 수식어를 걷어냈다 (Flow 자문).
VIDEO_TEXT_KEEP = ("The existing text {m} is locked to its graphic in perspective: same place, "
                   "same wording, crisp and legible throughout. Zero drift, zero duplication, "
                   "zero new text.")
VIDEO_NEGATIVE_KEEP = ("Avoid: adding any NEW text, letters, numbers, captions, subtitles, "
                       "watermarks or logos — the one existing HUD readout is wanted; keep it "
                       "sharp and unchanged. "
                       "Avoid: editing cuts or scene changes mid-clip — one continuous shot. "
                       "Avoid: people talking or mouthing words.")
# 시작 이미지에 홀로그램이 구워져 있을 때 — VIDEO_TEXT_KEEP 과 같은 원리의 유지 절.
# motion 이 홀로그램을 재언급하지 않으면 I2V 가 시작 프레임의 미세 발광 요소를 지우거나
# 뭉갠다 (숫자 readout 실측과 동일 계열). _build_motion_prompt 가 홀로 컷에 자동 첨부한다.
VIDEO_HOLO_KEEP = ("The start frame already carries a translucent glowing cyan hologram "
                   "standing in the real scene — keep it for the entire clip: luminous, "
                   "see-through, its thin wireframe edges crisp, locked to its position in "
                   "perspective as the shot moves. Never erase, dim, solidify or duplicate "
                   "it, and keep the real environment around it fully photoreal.")
# game 톤 영상 — RDR·차세대 게임 물리 엔진의 '무게감' 공식 (유레카 ragdoll·지형 흔적·재질별
# 반응을 영상 모델이 그릴 수 있는 현상으로 번역). 스타일은 이미지가 정하고 영상은 물리만 시킨다.
# game 톤 I2V — 룩 유지 절. 영상 모델의 실패 모드는 '실사로의 드리프트'다 (숫자·홀로그램
# 유지 절과 같은 패턴). 시작 프레임의 게임 렌더 룩과 캐릭터 정체성을 클립 내내 잠근다.
VIDEO_GAME_LOOK = ("The start frame is a stylized AAA game-engine render — hold that exact "
                   "in-game look for the entire clip: the same slightly idealized surfaces, "
                   "bold grade and bloom, and the character's exact face and outfit. Never "
                   "drift toward live-action photorealism, and never add any game interface, "
                   "minimap or on-screen indicators.")
# 만화 요약 톤 I2V — 실패 모드는 '정교한 애니로의 드리프트'다 (game 톤의 실사 드리프트와
# 같은 계열). 첫 프레임의 단순 플랫 셀 룩과 캐릭터 생김새를 클립 내내 잠근다.
# 인물 3D 톤 공통 룩 잠금 — story3d(오프라인 렌더 시네마틱)·toy3d(피규어)용.
# game 처럼 '엔진 룩'을 지목하지 않고 **시작 프레임 그대로**를 요구한다(톤마다 룩이 다르므로).
VIDEO_TONE_LOOK = ("Hold the exact look of the start frame for the entire clip — the same "
                   "materials, the same level of stylization, the same grade, and each figure's "
                   "exact form, proportions and outfit. Never drift toward live-action "
                   "photorealism, and never add detail, colour or texture that is not already "
                   "in the start frame.")
# 마네킹 계열(greycast·whitecast) — 위에 더해 **얼굴이 생기는 것**을 막는다.
# I2V 는 사람 머리로 인식하면 눈·코·입을 그려 넣는데, 이 톤들은 얼굴 없음이 정체성이라
# 그 순간 톤 자체가 무너진다 (실존 인물 회피라는 값어치도 같이 사라진다).
VIDEO_CAST_LOOK = ("Hold the exact look of the start frame for the entire clip — the same "
                   "untextured surfaces, the same faceted geometry, the same neutral grade. "
                   "Every head stays completely blank and featureless for the whole clip: no "
                   "eyes, nose, mouth, hair or expression ever appear on any figure. Never drift "
                   "toward live-action photorealism, and never add figures, props or detail that "
                   "are not already in the start frame. "
                   # 발광 강조가 붙은 컷 — 예전엔 'never add colour' 뿐이라 시작 프레임의
                   # 빨간 치수선까지 회색으로 바래거나 프레임마다 세기가 튀었다.
                   # 색을 '만들지 마라'와 '있는 건 지켜라'를 분리해야 둘 다 성립한다.
                   "Never add colour of your own — any accent glow already present in the start "
                   "frame keeps its exact hue and holds a steady, unflickering intensity for the "
                   "whole clip.")
# ── 🧩 조립 강조 (CLEAN→INFO) — 2026-08-18 실측으로 도입 ──────────────────
# 강조 컷을 두 장(CLEAN=강조 없음, INFO=강조 구움)으로 만들고, 영상은 CLEAN 에서 출발해
# INFO 를 도착 프레임으로 걸어 그래픽이 "조립되며" 나타나게 한다.
# 근거: · draw(그리라고만 지시) = 2.5초까지 빈 화면 → 기각 (2026-08-16)
#       · 도착 프레임을 주면 4단계 조립을 그대로 따라가고 끝 상태가 고정돼 사라질 수 없다
#       · 기존 방식(구워서 유지)은 4초 클립에서도 3초에 강조가 사라지는 사고가 있었다
INFO_EDIT_HEAD = """Use the reference image exactly as it is — the SAME scene, subject, lighting,
framing, camera and crop, changed in no way — and add ONE emphasis graphic onto it:

"""
INFO_EDIT_TAIL = """

The graphic is the only change. The rest of the image stays completely untouched and photoreal."""
# ⚠ 'anchor' 라는 단어를 쓰면 안 된다 — Seedance 가 문자 그대로 ⚓ 닻 아이콘을 그렸다
#   (2026-08-18 실측, 같은 프롬프트에서 Veo 는 점으로 해석). 'small glowing dot' 로 쓴다.
#   중간 도형 발명(UFO 같은 이중 고리)도 같은 실측에서 나와 금지문을 명시한다.
VIDEO_ASSEMBLE_TMPL = """Animate the provided start frame into the provided last frame.

Over the clip, ONE {accent} emphasis graphic assembles itself onto the scene, arriving exactly
at the last frame's completed state: {stages}. The assembly is quick and decisive — it is
already complete by one third of the way into the clip, matching the last frame's state
exactly, and for the entire remainder everything holds perfectly steady. Never spread the
assembly across the whole clip; the long tail of the clip is a steady hold, not a slow build.
Nothing disappears once drawn.

The scene itself stays exactly as it is — the graphic is the only thing that changes, locked to
the structure in correct perspective as it assembles, thin and crisp like a light-emitting
instrument overlay. Never invent any other shape, icon, symbol, ring or emblem — draw only the
elements described, exactly as they appear in the last frame.
Camera: very slow, barely perceptible dolly push-in.
No letters, digits or words beyond those already present in the last frame.
No flicker, no fade-out.
{audio_line}"""
# ── 조립 문법 이원화 (2026-08-19, 2편 실측) ──────────────────────────
# 구조형(치수선·화살표·카운트·게이지·그래프·윤곽·영역): "부품이 순서대로 그려진다"고 시키면
# 시댄스가 '그리는 중'을 핑계로 없는 기하를 부연한다 — #9 ㄱ자 브래킷·가로 팔 발명,
# #7 화살표 6초 내내 요동, #8 대형 링 발명 + x3 끝프레임 스냅.
# → 구조형은 **완성체가 제자리에서 페이드인(어둡게→밝게)하고 형태 동결**.
# 경로형(궤적·흐름·동선·파동·골격·하중·회전·뻗음): 빛이 경로를 달리는 게 본질이라 성장 유지
# (#4 trajectory 성장 조립이 깨끗하게 성공한 실측).
ASSEMBLE_STAGES = {
    # 사용자 최종 결정 (2026-08-19 3차): 그리기도 비행도 아니고 **제자리 발생** —
    # "측정 완료된 선이 저 위치에서 생기는 느낌". 진입식은 초반에 대각선으로 방황했고
    # (같은 날 실측), 이동이 없으면 방황할 경로 자체가 없다. 순서는 선 먼저, 수치 다음.
    "measure": "the complete dimension line — extension lines, shaft and both arrowheads — "
               "materializes exactly in its final position, fading up from nothing to full "
               "brightness in well under a second, every part appearing where it belongs "
               "without moving, sliding, growing or approaching from anywhere; the value then "
               "fades in, breaking the line at its centre. From the moment it appears nothing "
               "shifts by a single pixel, and nothing else is ever added: no bracket, no "
               "second arm, no corner piece, no outline around the object",
    # 성장형(1편)도 비행 착지형(2편 #7)도 기각 — 물건처럼 날아와 얹히는 게 어색하다.
    # 가리키는 형태 그대로 제자리 페이드인 — 사용자 결정 2026-08-19.
    "arrow":   "the complete arrow, shaft and broad head formed as one piece of glowing "
               "translucent light, fades in already pointing at its target in its exact final "
               "position — dim to bright, its shape, angle and position frozen from the first "
               "moment; it never flies in, grows, slides, rotates or reshapes, and it is never "
               "a physical wooden or metal arrow",
    # 동시 점등은 과교정이었다 — 순차 점등 자체는 2편 #8 에서 깨끗하게 성공했고
    # 사용자도 "순차 빠르게 점·점·점"을 원함 (2026-08-19). 발명 금지만 유지한다.
    "count":   "the dots light up one after another in quick succession — one, then the next — "
               "each already complete and sitting in its exact final position, never moving or "
               "resizing; the running total fades in together with the last dot and never "
               "recounts; no new ring, beam or line is ever invented",
    "flow":    "the band's origin brightens first, then the broad band grows along the real path "
               "of the flow to its outlet",
    "gauge":   "the complete empty gauge — track, outline and fine ticks — fades in first in its "
               "exact final position, then the fill rises once to its final level and holds; "
               "the frame itself never moves or reshapes",
    "graph":   "the complete graph — axis, ticks, curve and wash — fades in together in its "
               "exact final position, dim to bright; nothing is drawn stroke by stroke and "
               "nothing shifts once visible",
    "extent":  "the nearest block lights first, then the identical blocks light one after another "
               "down the whole run",
    "outline": "the complete outline fades in already wrapped around the subject's silhouette, "
               "dim to bright — never traced stroke by stroke, never redrawn or reshaped",
    "zone":    "the complete boundary and its translucent interior tint fade in together in "
               "their exact final position, dim to bright — never traced stroke by stroke, "
               "never resized",
    "spin":    "the glowing dot lights first where the sweep begins, then the helical line "
               "winds around the axis turn by turn, the arrowhead forming last",
    "wave":    "the origin dot lights first, then the rings appear one after another from the "
               "innermost outward, each settling before the next",
    "skeleton": "the members light up progressively along their real paths, spreading from where "
                "the network begins until the whole system is lit",
    "loadsplit": "a glowing dot lights where the load enters, the stream grows down to the split, "
                 "then both branches grow together down the flanks, the arrowheads forming last",
    "trajectory": "a glowing dot lights at the launch point, the arc grows along its full curve "
                  "to the impact point, the arrowhead and the ground ring forming last",
}
# 조립 제외 — 아래 도구는 빛을 얹는 것이 아니라 **장면 자체를 바꾸는 것**이라
# CLEAN→INFO 사이를 그려서 갈 수 없다. 모델이 화면 재구성(모핑·전환)으로 때운다:
#   versus = 화면 분할 (1편 #12 실측: 분할선이 흘러다니고 없던 번개가 생김)
#   scale  = 비교 물체가 새로 등장 (1편 #3 실측: 코끼리가 걸어 들어오고 마릿수 어긋남)
# → 기존 방식(이미지에 구워서 유지)으로 폴백.
# measure 는 제외했다가 되살렸다 (2026-08-19 같은 날): "선이 그려지고 수치가 나오는" 연출을
# 사용자가 원해서. 낙서 리스크는 남는다 — 실사 장면에서 잔선(차체 윤곽·포신) 낙서 실측 있음.
# 수치가 안 깨지는 이유: 모델이 그리는 게 아니라 도착 프레임의 구운 숫자로 수렴하기 때문.
ASSEMBLE_SKIP = {"versus", "scale"}
ASSEMBLE_STAGE_DEFAULT = ("the complete graphic fades in as one piece in its exact final "
                          "position, dim to bright, its shape frozen from the first moment — "
                          "never drawn part by part, never sliding or reshaping, and no extra "
                          "shape is ever invented")

VIDEO_ANIME_LOOK = ("The start frame is a simple flat cartoon drawing — hold exactly that look "
                    "for the entire clip: the same thick even outlines, the same flat colors "
                    "with no shading or gradients, the same round simple faces with dot eyes, "
                    "and each character's exact hair, face and outfit. Never drift toward "
                    "detailed anime art, 3D, cel shadows, glossy eyes or photorealism, and never "
                    "add new characters, props or background detail that is not already there.")
# 단면 컷 기하 잠금 — 단면·컷어웨이는 이미 이미지에서 갈라져 있다. 영상이 그걸 '다시 여는'
# 실패(껍질이 젤리처럼 휘거나 녹으며 속이 드러남)를 막는다.
# ⚠ '아무것도 바뀌지 않는다'로 쓰면 안 된다 — I2V 템플릿의 "Motion 이 이 컷의 요점"과
#   정면충돌해 미세 움직임만 남는다(HUD 네거티브 충돌 전례와 같은 계열). 그래서 마지막
#   문장으로 'Motion 에 지목된 하나'만 예외를 열어둔다.
VIDEO_XSECTION_LOCK = ("The sectional reveal is already complete in the start frame. Keep the "
                       "outer shell, the cut boundary, the exposed material thickness and every "
                       "internal part not named in Motion rigid and fixed in place. Only the "
                       "single component or flow explicitly named in Motion above may move.")
# 잠금을 끈 컷 — '겉이 걷히며 속이 보이는' 연출을 한 컷 안에서 시도한다.
# 완전 방임은 위험하다: 720p 가 절단면 뒤를 새로 그리면 프레임마다 달라진다([5-3]).
# 그래서 **여는 것은 허용하되, 속은 시작 프레임에 이미 있는 것만** 이라고 못박는다.
VIDEO_XSECTION_OPEN = ("The outer shell opens to reveal what is inside: it parts, lifts away or "
                       "fades to transparent ONCE, smoothly and continuously, and never closes "
                       "again. The interior revealed underneath is exactly the structure already "
                       "present in the start frame — same parts, same positions, same proportions. "
                       "Everything not named in Motion above stays rigid and fixed in place.")
VIDEO_XSECTION_OPEN_NEG = (" Avoid: inventing internal structures, rooms, parts or detail that are "
                           "not already visible in the start frame; the interior rearranging, "
                           "duplicating or drifting; the shell opening and closing repeatedly; "
                           "the object melting, stretching, swelling or turning to liquid.")
VIDEO_XSECTION_NEGATIVE = (" Avoid: the object bending, melting, stretching, swelling, warping or "
                           "peeling open to reveal its inside; a moving cutting plane; the cut "
                           "boundary or wall thickness changing; internal parts rearranging, "
                           "duplicating, disappearing, or new internal structures that are not "
                           "already in the start frame.")
# 분해뷰 컷 — 부품은 이미 이미지에서 벌어져 있다. 영상은 '직선 이동 한 번'만 시킨다.
# 부품이 회전하며 흩어지는 것이 이 연출의 대표 실패다 (조립 관계가 안 읽힘).
VIDEO_EXPLODED_KEEP = ("The components visible in the start frame are the complete set for this "
                       "shot. Every component stays rigid, intact and visible the whole time, and "
                       "may only travel straight along its own assembly axis exactly as Motion "
                       "describes — its shape, orientation, scale and order never change.")
VIDEO_EXPLODED_NEGATIVE = (" Avoid: components spinning, tumbling, scattering, bursting outward, "
                           "arcing sideways, crossing each other's paths, floating free, "
                           "duplicating, disappearing or deforming; and avoid any second "
                           "assembly or disassembly action after the first one finishes.")
# 도착 프레임(체인) — lastFrame 을 '두 번째 액션'이 아니라 '지금 이 한 동작의 물리적 종착점'으로
# 규정한다. 그래야 "한 클립에 큰 액션 하나" 원칙과 싸우지 않는다. 크로스페이드·모핑으로
# 때우는 것만 막는다 (그건 이음매가 아니라 편집 트랜지션이라 원테이크가 깨진다).
# 두 프레임이 **다른 공간·다른 시대**일 때. 물리적으로 걸어갈 수 없는 거리라
# "실제 이동으로 도착하라"가 성립하지 않는다 — 그러면 모델이 크로스페이드나 모핑으로
# 때우고, 그건 우리가 금지한 실패다. 대신 **시야를 가리는 매개**를 하나 통과시켜
# 그 순간에 장면을 바꾼다 (Flow 자문 2026-08-12: 매치컷 기반 공간 전이).
# {drive} 슬롯 — 컷 성격에 따라 갈린다.
#   일반 컷: Motion 이 장면을 크게 바꾸는 게 목적이다
#   강조 컷: 정반대다. 그래픽은 고정이고 빛·먼지만 움직인다
# 예전엔 앞엣것만 있어서, 강조를 고정하라고 해놓고 같은 프롬프트에서 "장면을 크게
# 변형시켜라"고 요구했다 (Flow 자문 2026-08-12 에서 지적받아 분리).
VIDEO_DRIVE_CHANGE = ("The Motion above is the whole point of this shot: let it visibly "
                      "transform the scene as described, not just idle micro-movement.")
VIDEO_DRIVE_HOLD = ("The scene's geometry is already correct and must stay that way. "
                    "Put the motion entirely into light, dust, haze and the one change named "
                    "above — nothing solid shifts, grows, bends or rearranges.")

VIDEO_LAST_FRAME_BRIDGE = ("The provided last frame is a DIFFERENT place from the start frame — "
    "you cannot walk there. Do not try to travel between them, and never blend them with a "
    "crossfade, dissolve, double exposure or morph. Instead the shot passes through ONE thing "
    "that completely covers the lens: the camera moves into a narrow gap, behind a passing "
    "foreground surface, through a doorway, into a swirl of dust, or into a flare of light. "
    "Timing is exact — the frame is 100% obscured at the halfway point of the clip. "
    "Before that moment everything belongs to the start frame; after it the scene IS the last "
    "frame, already settled and stable, and it holds there to the end. The camera keeps moving "
    "in the same direction throughout so it reads as one continuous move rather than a cut, "
    "and the two scenes never appear on screen at the same time.")

VIDEO_LAST_FRAME_ARRIVE = ("The provided last frame is where this same continuous shot physically "
                           "ends. The Camera and the single Motion above are the whole transition: "
                           "carry them through until the framing and the state of the scene match "
                           "that last frame, and let everything Motion does not change stay as it "
                           "is. Reach it by real camera movement and real physical action — never "
                           "by a crossfade, dissolve, double exposure, ghosted blend, morph, "
                           "sudden replacement or teleport, and never by adding a second event.")
VIDEO_GAME_PHYS = ("Physical weight everywhere, like a cutting-edge game physics engine: "
                   "bodies move with mass and momentum, staggering and catching their balance "
                   "when pushed; cloth, hair and fur react to motion, wind and wetness; "
                   "footsteps and wheels press real tracks into snow, mud and dust, and grime "
                   "clings to bodies and gear; muscles shift visibly under skin as humans and "
                   "animals move; objects collide and respond by their material — wood "
                   "splinters, metal dents, water wakes and foams. Every impact reads with "
                   "weight; nothing floats or slides weightlessly.")

# 시작 프레임이 있을 때(I2V) — 공식 가이드: "이미지가 이미 피사체·배경·구도·스타일을 정의하므로
# 프롬프트는 액션·카메라·오디오에 집중하라." 장면을 다시 묘사하면 이미지와 싸운다.
# 단 '아무것도 바꾸지 마라'는 금지 — 컷의 존재 이유가 대본상 '변화'(출혈이 멈춤, 수지가 굳음)인데
# 그 지시가 Motion 을 눌러 미세 움직임만 나온다. 스타일·정체성만 잠그고 변화는 허용한다.
# 첫 프레임부터 움직임 진행 중 — 쇼츠는 첫 0.5초 정지면 스와이프당한다.
MOTION_PROMPT_I2V = """Animate the provided start frame.

Camera: {camera}
Motion: {motion}

Keep the start frame's style, subject identity, lighting and color grade.
{drive}
The motion is already underway on the very first frame — never open on a frozen,
settling shot.
Deep depth of field: everything from foreground to background stays in sharp focus —
no shallow-focus blur, no bokeh, nothing softened out.
Keep straight edges straight and parallel lines parallel — no warping, bending,
melting or rubbery distortion of solid surfaces as the camera moves.
{tempo}

{audio}
{negative}"""


# ── 톤 프리셋 (PRD 6-4). config의 img_style_override로 덮어쓸 수 있다 = 재빌드 없이 튜닝 ──
STYLE_DEFAULTS = {
    # ── 자료 이미지 톤 ─────────────────────────────────────────────────
    # 대본을 컷으로 나눠 만드는 톤들과 달리, 본편 중간에 끼워 넣을 **자료 화면**을 만든다.
    # 카메라로 찍은 장면이 아니라 '책상 위에 놓인 물건'을 위에서 본 그림이다.
    #
    # collage — 손으로 오려 붙인 다큐 콜라주. 사건·역사·미스터리 채널의 자료 화면.
    # 종이 색을 한 톤으로 통일하지 않는 것이 핵심이다. 크림·표백지·마닐라를 섞어야
    # 여러 출처에서 오려낸 것처럼 읽힌다 (한 톤이면 인쇄물처럼 납작해진다).
    "collage": """Style: a hand-cut documentary paper collage, photographed flat from directly above
on a plain table. Aged newsprint and archival map surfaces as the base, black-and-white halftone
photograph cutouts with rough scissor-cut edges, torn paper edges, masking tape fragments,
typewriter caption strips, rubber stamp marks, and red string with brass pins where the story
calls for connections. Desaturated archival palette of tan, ink black and halftone grey with ONE
hot red signal accent and a restrained mustard yellow secondary — no other colours.
Vary the paper stock from piece to piece rather than one flat shade: lighter cream and bleached
newsprint scraps sit alongside darker aged-tan and manila pieces, so it reads as assembled from
many different real papers. Visible print grain and paper fibre, matte throughout, flat even
documentary lighting with soft drop shadows separating each cut layer from the one beneath.
One dominant element holds about seventy percent of the visual weight, two or three supporting
pieces at most, and generous empty paper around them.
Written matter follows one rule: nothing longer than two words is ever spelled out, because
readable sentences always come out misspelled. Handle it by size. Body copy and columns are set
in type far too small to read, so they register as grey texture and nothing more — never as
redaction bars, or the page turns into a censored file instead of a newspaper. Anything printed
large enough to read — a headline, a caption line — is covered by a solid black bar instead,
and there are at most two or three such bars in the whole frame. Only a short rubber stamp or a
bare year appears as real legible characters. Never print the words used to describe a piece onto
the piece itself: a caption strip is blank, it never reads "caption".""",

    # mapboard — 낡은 종이 지도가 화면 전체를 채운다. collage 와 재질은 같은 계열이지만
    # 여기서는 지도가 조각이 아니라 주인공이고, 읽어야 할 것은 지명이 아니라 **경로와 위치**다.
    # 실제 지리는 부정확하게 나온다 — 정확한 국경·도시가 필요하면 지도 API 를 써야 한다.
    "mapboard": """Style: an old printed paper map laid flat and photographed from directly above,
filling the frame. Fine engraved contour lines, hatched relief, a faint printed grid, and a
compass rose or a scale bar in one corner. The paper is aged and softly creased along old fold
lines, its edges worn, one corner slightly lifted. Restrained cartographic palette: cream and
warm tan land, pale blue-green water, thin sepia linework, with ONE hot red signal accent used
only for the route, the pins and the marked points — no other saturated colour anywhere.
Brass pins press into the marked places and taut red thread runs between them where the story
connects two points. Matte paper fibre and visible print grain, flat even documentary lighting,
soft shadow under the pins and the lifted corner.
Place names and legends belong to the printed map itself and are set far too small to read,
registering as fine texture only. Nothing is ever labelled on top of the map: the pins and the
marked points carry no name tags, no callouts and no captions, and the words used to describe
where the route starts or ends are never written onto the paper. A bare year or a one-word
rubber stamp may appear legibly; nothing else does.
The route and the marked points are the only things the eye is meant to follow.""",

    # vector — 평면 벡터 도해. 종이 계열(collage·mapboard)과 정반대 재질이다.
    # 실물을 흉내내지 않고 **뜻만 남긴다** — 원리·비율·구조를 설명하는 자리.
    # blueprint(청사진)·planline(평면 선화)과 다른 점: 저 둘은 선, 이건 색면이다.
    "vector": """Style: a flat vector explainer illustration, the kind used in a modern
documentary channel's motion graphics. Everything is built from clean geometric shapes filled
with flat solid colour — no photographic texture, no shading gradients, no drop shadows, no
perspective depth. Forms are simplified down to what the idea needs and nothing more, drawn head
on or in clean isometric, with rounded corners and confident even line weights where outlines
appear at all.
A tight palette of four colours at most: a light neutral ground, two muted mid-tones carrying
the main shapes, and ONE saturated accent reserved for the single thing being explained.
Generous empty space around the subject; the composition reads instantly at a glance and stays
legible when the frame is small.
No text, no numbers, no axis labels, no legends — the shapes alone carry the meaning and any
wording is added later in editing.""",

    # productshot — 배경을 지우고 물건 하나만 세운다. labmacro 와 갈리는 지점은 '무대'다:
    # labmacro 는 작업대 위에서 무언가가 일어나는 장면이고, 이건 아무 일도 일어나지 않는다.
    # 사물 소개 채널에서 "이게 그 물건입니다" 한 장으로 끝내는 자리.
    "productshot": """Style: a clean studio product photograph. The object stands alone on a
seamless background of one flat neutral tone — pale grey, off-white or a single muted colour —
with nothing else in frame: no props, no hands, no table edge, no environment.
Large soft key light from one side with a gentle fill on the other, a subtle rim of light
separating the object from the ground, and one soft contact shadow directly beneath it.
Every material reads honestly: brushed metal stays metal, rubber stays matte, glass stays
translucent, fabric keeps its weave. Sharp focus front to back so the whole object is legible,
shot straight on or slightly above at a natural product angle.
No brand marks, no logos, no model names, no printed text of any kind on the object or the
background.""",

    # chalkboard — 칠판에 손으로 그린 설명. vector 와 같은 '도해'지만 온기가 있다.
    # 사람이 그리는 중인 화면이라 교육·과정 설명에서 신뢰가 붙는다.
    "chalkboard": """Style: a chalk drawing on a large dark slate board, photographed straight on
so the board fills the frame. Deep charcoal-green slate with the faint cloudy smears of earlier
work wiped away, fine chalk dust caught in the surface.
Everything is drawn by hand in white chalk with a slightly uneven line that thickens and thins,
the pressure visible, edges softly crumbling. One or two colours of chalk at most beside the
white — a pale yellow and a muted red-orange — used only to pick out the single thing that
matters. Arrows, brackets and simple diagrams, drawn quickly but clearly, the way someone
explains a thing while talking.
Warm low side light rakes across the board so the chalk catches and the slate stays matte.
Nothing longer than two words is ever written out; the diagram carries the meaning and any
wording is added later in editing.""",

    # xray — 겉을 지우고 속만 남긴다. 단면(xsection)과 다른 점: 자르지 않고 통째로 비춘다.
    "xray": """Style: an X-ray radiograph. The subject is seen straight through, rendered only as
density: dense material reads bright and solid, thin or hollow material fades toward black, and
the surrounding air is pure black. No surface colour, no texture, no reflections, no lighting
direction — only the shadow the material casts on the plate.
Cool monochrome throughout, black through blue-grey to near-white, with the faint bloom and fine
grain of a real radiographic plate and a slight halo around the densest edges.
The whole object stays inside the frame with black space around it, shot flat and square with no
perspective, the way a plate is taken. Internal parts, screws, wires, bones and cavities are the
point and read clearly through the outer shell.
No text, no scale markers, no annotations of any kind.""",

    # story3d — 역사 재현 내레이션 채널의 3D 시네마틱 (Yarnhub 계열).
    # game 톤과 갈리는 지점은 '무엇처럼 찍혔나'다: game 은 게임 엔진 실시간 캡처 룩이라
    # 스크린스페이스 반사·LOD·블룸 같은 엔진 흔적이 정체성이고, 이쪽은 오프라인 렌더라
    # 그런 흔적이 없다. 대신 **영화 렌즈**가 정체성이다 — 얕은 심도, 색조 대비 조명.
    "story3d": """Style: a rendered 3D cinematic from a history-narration film — stylized realism,
not a photograph and not a cartoon. Characters are modelled with believable anatomy and clothing
but slightly simplified: skin is smooth and matte with soft subsurface warmth, pores and blemishes
left out, faces readable and expressive at a glance.
Shot as if through a real cine lens: shallow depth of field with the subject sharp and everything
behind it falling into soft bokeh, a mild telephoto compression, subtle lens bloom on highlights.
Lighting carries the mood and does most of the storytelling — a warm key from one side against a
cool ambient, hard rim light separating the figure from the dark, dusk blues, firelight orange,
or the flat grey of overcast weather. Rich but controlled colour grade with deep shadows that keep
detail, gentle film grain, no crushed blacks.
Period props, uniforms, vehicles and terrain are accurate and worn in, with dust, mud and scuffs
that read at a glance. Staged like a film, not like gameplay: no interface, no on-screen markers,
no engine artefacts, no screen-space reflections.""",

    # toy3d — 통통한 미니어처 피규어로 역사·사건을 연기시키는 톤 (Mitsi Studio 계열).
    # 무거운 소재를 가볍게 만드는 장치다. 재질(무광 비닐)과 비율(큰 머리·짧은 팔다리)이
    # 정체성이고, 조명만은 진지한 영화처럼 간다 — 그 낙차가 이 톤의 힘이다.
    "toy3d": """Style: a rendered scene acted out by chubby miniature collectible figures.
Proportions are fixed and identical for every character, in every shot: the head alone is about
two fifths of the whole figure's height, so the body reads roughly two and a half heads tall in
total. The head is a smooth rounded egg with no neck at all, sitting straight on a short barrel
torso that is as wide as it is tall. Arms are short stubs reaching only to the waist, ending in
plain mitten hands with no separate fingers; legs are stubby cylinders barely longer than the
feet. Nobody is slim, nobody is tall, and these ratios never vary between characters or scenes.
The face is simple but never blank or creepy. The nose is a small soft rounded bump, wide and
gentle, never pointed or beaked. The eyes are large glossy black ovals set well apart, each with
one bright specular highlight so they read as alive, not as pinpricks. Thick sculpted eyebrows sit
above them and carry the whole expression — angled down for anger, raised for surprise, level for
calm. Cheeks are full and softly flushed. There is no mouth and no teeth; the brows and the head
angle do all the acting.
Everything is moulded from soft matte vinyl and plastic: rounded edges everywhere, no sharp
corners, faint mould seams, a slight satin sheen on the raised surfaces and clean flat colour
underneath. Clothing, caps and gear are moulded onto the body as part of the toy rather than as
real cloth. Props, vehicles and buildings are the same toy world at the same chunky scale.
The lighting is the opposite of toylike and carries all the weight: dramatic cinematic key light
with deep shadow, hard rim separation, atmospheric haze, strong colour contrast between a warm
key and a cool ambient. Shallow depth of field with soft bokeh behind, shot at figure eye level
like a film. The contrast between the cute forms and the serious light is the whole point.""",

    # whitecast — greycast 의 밝은 짝 (Cipher 채널 실측 2026-08-15).
    # 갈리는 지점 셋: ①어두운 무대가 아니라 **밝은 흰 세계** ②옷이 암시가 아니라 **실제 형태**
    # (전술조끼·패딩·정모) ③총구 연기·파편 같은 **거친 입자**가 허용된다.
    # 얼굴이 없는 것은 같다 — 그래서 실존 인물·부대 마크 문제를 똑같이 비켜간다.
    # 용도: 총격전·재난·사고처럼 **공개된 사건의 액션**. greycast 는 조용한 사건 재구성.
    "whitecast": """Style: a scene rebuilt as a clean white low-polygon model world under bright,
even light. Buildings, roads, cars, furniture and props are all smooth untextured white or pale
grey with simple faceted geometry and soft shadows — a model of the place, not the place itself.
The figures are mannequins at true human proportions with plain featureless heads: no eyes, no
nose, no mouth, no hair. Unlike the world around them they DO wear real, readable clothing —
tactical vests, jackets, uniform caps, boots — but always in flat blacks, greys and whites with no
colour and no logos. Weapons, bags and handheld objects carry real shape and detail.
Lighting is cool and directional: one soft low-angle key laying long soft shadows across the white
surfaces, so every plane reads at a slightly different brightness and the faceted forms stay
legible. Deep shadow where the light does not reach. Coarse physical particles are allowed where
the story needs them — a puff of muzzle smoke, a few chunks of debris — never fine sprays or sparks.
Beyond the staged area everything falls away to pure black. Only when the place itself matters to
the story — a snowfield, a yard, a corridor — is that setting built out in the same white model
material.
Shot like documentary reconstruction: eye-level or high overhead, calm framing, shallow depth of
field.
The world itself carries no colour — only the neutral scale of white to black. The ONE exception
is highlight light: when a highlight instruction below asks for one, that accent hue appears as
emissive light on exactly the thing it names. Never invent a highlight of your own, never pick a
different hue, and nothing else in the frame ever takes colour. With no such instruction the
picture is completely monochrome. Where that accent light
touches a surface it leaves a soft bloom, and the one or two nearest forms pick up a faint wash of
the same hue — it behaves like light in the room, not like a graphic pasted on top.""",

    # greycast — 얼굴 없는 회색 마네킹이 연기하는 무채색 무대 (레퍼런스 실측 2026-08-15).
    # **실존 인물 문제를 근본적으로 푸는 톤이다.** game·story3d·toy3d 는 얼굴을 그리므로
    # "실제 인물을 닮게 그리지 마라"는 금지 규칙에 기대야 하지만, 이 톤은 얼굴이 아예 없어
    # 닮을 수가 없다 → 범죄·사건·근현대사처럼 실존 인물이 나오는 소재에 이게 정답이다.
    # 정체성 셋: ①세계 전체가 한 재질(무광 회색·각면) ②얼굴 없음 ③대상 하나만 진짜 질감.
    "greycast": """Style: a scene acted out by faceless grey figures, staged in a dark room.
Every figure is a smooth matte grey-white artist's mannequin at true human proportions, built from
low-polygon faceted forms with visible flat planes at the shoulders, elbows and knees, and a plain
angular head with NO face at all — no eyes, no nose, no mouth, no hair. Clothing is suggested only
by a slight change of tone or a faceted collar, never real fabric.
The set around them is made of the same material: walls, ceiling, windows, doors, furniture,
vehicles and props are all the same untextured matte grey at the same faceted level of detail,
like a model built to explain what happened. When the scene is an interior the set is a box with
one wall removed; when it is outdoors or a single moment, the figures and props simply stand on a
bare dark floor with the light pooling around them. Either way, beyond the edge of the staged area
everything falls away to pure black.
Lighting is cool and cinematic: a soft overhead key pooling on the floor, deep shadow around it, a
faint rim separating the figures from the dark, gentle haze in the air. Shallow depth of field,
calm eye-level framing, generous empty space.
Entirely monochrome — the world itself carries no colour. The ONE exception is highlight light:
when a highlight instruction below asks for one, that accent hue appears as emissive light on
exactly the thing it names. Never invent a highlight of your own, never pick a different hue, and
nothing else in the frame ever takes colour. With no such instruction the picture is completely
monochrome. Where that accent light touches a surface it leaves a
soft bloom, and the one or two nearest forms pick up a faint wash of the same hue — it behaves
like light in the room, not like a graphic pasted on top.
The ONLY thing allowed real texture and printed detail is the single object the story is about;
everything else stays blank grey.""",

    # blackstage — 검은 무대 위에 사물 하나 (레퍼런스 실측 2026-08-15).
    # 정체성은 셋이다: ①순수 검정 배경 ②흰 무광 캐스트(자기 색이 없다) ③시안 발광 곡선 하나.
    # claysection(밝은 스튜디오·단면)·productshot(사진 룩)과 갈리는 지점이 '검은 무대'다.
    # 글자는 넣지 않는다 — 라벨·제목은 편집에서 얹는다(이미지 모델이 글자를 뭉갠다).
    "blackstage": """Style: a single subject presented alone on pure black, like an exhibit lit
in a dark room. The subject is rendered as a smooth matte white plaster or marble cast — no
colour of its own, fine sculptural detail, soft self-shadow, clean edges.
One soft key light from above and slightly in front picks it out; everything around it falls to
true black with nothing else in frame — no room, no table, no horizon.
The only colour in the picture is a single luminous cyan (#22D3EE) accent: one thin glowing cyan
curve sweeping through the empty space behind the subject, a faint glowing cyan arc on the ground
beneath it, and a soft cyan bloom where that light spills. Nothing else is coloured.
Very fine pale dust motes drift in the dark. Sometimes a dark perspective grid on the floor drawn
in thin, barely visible lines.
Composed centred and symmetrical with generous empty space around the subject.
No text, no lettering, no numbers anywhere in the frame.""",

    # tabletop — 엔지니어가 책상 위에 세운 설명용 모형 (@solveyoutube 계열, 884프레임 실측).
    # 이 톤의 힘은 **스케일 대비**다: 연필·커피잔·접착제가 모형 옆에 놓여 있어서
    # "이건 실제가 아니라 설명하려고 만든 모형"이 한눈에 읽히고, 그래서 무거운 주제도
    # 차분하게 볼 수 있다. labmacro(작업대 위 실험)·claysection(배경 없는 단면)과 갈리는
    # 지점이 바로 그 책상과 대비 소품이다.
    "tabletop": """Style: a 3D-rendered miniature world — the scene built at model scale and
filmed as if it were real, but never pretending to be a photograph. No table, no base, no desk,
no room around it: the world simply fills the frame and its edges run past the crop or fade into
soft darkness. The sky or background behind is one flat empty tone, never a real environment.
Everything is one smooth matte material with no photographic texture at all — sculpted plaster,
soft clay, unpainted resin, sometimes pale wood or stacked card contours for terrain. Edges are
clean, detail is stripped to only the shapes the explanation needs, and surfaces take light
softly with no gloss and no grain. It reads as something someone built to explain a thing.
The whole frame sits in ONE dominant colour that carries the mood — deep blue-grey night, a flat
warm red, a pale cold white — with everything in the scene tinted into it, and ONE contrasting
accent used sparingly: a thin glowing line tracing a route, small warm points of light marking
positions, a lit window, a single burning flare. Those glowing marks are the only saturated thing
in the frame and they are what the eye follows.
Lighting is cinematic and clean: a soft key raking across from one side, the far side falling
away into darkness, gentle atmospheric haze in the deepest shadows.
Shot from above at a raked three-quarter angle, close to isometric, looking down into the
scene; sometimes dropped right down to figure height inside it. Shallow depth of field with a
strong miniature falloff — a narrow band in focus and everything nearer and further melting
into bokeh, which is what makes the scale read.
Any human figures are unpainted miniature figures with completely blank faces — smooth, featureless,
never eyes, never expressions.
No hands, no tools, no clutter, no brand marks, no text — the world alone.""",

    "snap": """Style: rendered as an ordinary snapshot taken on a mid-range phone,
the kind posted to an online community board. Not photography — just a photo someone took.
Default phone camera, auto exposure, auto white balance.
Slightly crooked framing, subject not perfectly centered, mild handheld shake, deep depth of field.
Whatever light the scene would actually have — ceiling fluorescent, warm bulb, night phone flash,
mixed color temperature, blown highlights, noise in shadows.
Slight JPEG artifacts, no retouching. Mundane and unstaged rather than art-directed.""",
    "cine": """Style: rendered as a cinematic film still. Anamorphic framing,
strong motivated key light with deep falloff, rich shadow detail, volumetric haze,
muted teal-and-amber grade, subtle film grain. Shot on a full-frame cinema camera
with a fast prime. Composed and deliberate — dramatic, but with believable real-world texture.""",
    "archive": """Style: rendered as a vintage black-and-white archival photograph,
scanned from an old print. Pure monochrome — no sepia, no color cast.
Faded blacks and soft highlights, heavy film grain, dust specks and faint scratches,
gentle vignetting, slightly soft period-lens focus, documentary framing.
Looks like it was shot decades ago on black-and-white film of its own era.""",
    "illust": """Style: a flat vector illustration / graphic-novel panel.
Bold clean linework, limited flat color palette, simple geometric shapes,
minimal cel shading, no photographic texture.
Strong readable silhouette that still works at thumbnail size.""",
    # ⑭ game — AAA 오픈월드 게임 시네마틱 (GTA·RDR류 룩. 게임 이름은 프롬프트에 쓰지 않는다 —
    # 모델이 거부하거나 트레이드 드레스를 베낀다). 유일하게 얼굴이 나와도 되는 톤:
    # 스타일라이즈드 캐릭터라 실사 재연보다 거부감·초상권 부담이 적다 (2026-08-10 결정).
    # 미니맵·수배 별점 등 게임 HUD 는 IP 코드라 넣지 않는다.
    "game": """Style: rendered like a cinematic sequence from a modern AAA open-world game —
stylized realism, not a photograph and not a cartoon. Clean, slightly idealized surfaces
with real material response; skin reads lifelike but subtly smoothed, like a high-end
game character. Bold confident lighting that follows the scene's own light source —
strong sun with soft bloom, thick fog or snow haze, golden-hour rim light, or saturated
neon and practical lamps at night. Rich vivid color grade, deep contrast, faint grain.
Looks captured from the running game engine in real time: subtly softened anti-aliased
edges, screen-space reflections on wet and glossy surfaces, gentle bloom lifting off
bright speculars, and slightly simplified detail in the far distance like game LOD.
Dense lived-in set dressing: era-appropriate props, wear and clutter that tell a story.
Physics reads in every frame, like a cutting-edge game engine: mud, dust, snow and rain
visibly cling to characters, animals and gear; terrain holds footprints and wheel tracks;
cloth and hair hang and fold with real weight.
People may appear as clearly stylized game characters with readable, expressive faces
and strong silhouettes — never resembling any real, famous or public person.
Third-person cinematic staging, like a AAA game cutscene — no game interface, no minimap,
no on-screen indicators.""",
    # ⑮ anime — 만화·애니 '한 편 요약' 컨셉. 캐릭터 시트를 참조 이미지로 물려
    # 여러 컷에 같은 인물을 유지한다 (CHAR_SHEET_LINE). 시트가 없으면 캐논 문구로 폴백.
    # ⚠ 원작 그림체·캐릭터 디자인을 베끼지 않는다 — 창작 캐릭터로 '느낌만' 만든다 (FACE_ANIME).
    "anime": """Style: a simple hand-drawn Japanese cartoon frame.
Rounded characters at roughly 2.5-head-tall proportions, round faces, small black dot eyes,
simple curved mouths, thick dark outlines of even width all the way around.
Bright flat colors and completely flat cel style — no shading, no gradients, no gloss,
no rendered depth, no painterly texture, no fine linework detail.
Plain uncluttered backgrounds carrying only the few props the moment actually needs.
Cartoon emotion symbols belong to this language and are drawn as simple flat shapes:
sweat drops, tear streams, spark and anger marks, speed lines and pressure lines.""",
    # ⑬ docu3d — 다큐 설명형 3D. tech3d(인포그래픽)·arch3d(포토리얼)와 다른 제3의 길:
    # 저폴리 면이 보이는 '그래픽한' 모델 + 탈채도 청회색 + 시안 발광. 여백이 넓고 대비가 세다.
    "docu3d": """Style: rendered as a cinematic on-location 3D reconstruction — the camera is
standing at the real site, not looking at a model on a table. The subject sits in its actual
environment with real ground, weather and atmosphere: haze hanging in the air, light raking
across surfaces, terrain and structures receding into depth behind it. Real scale, real place.
Materials keep their own character — pale limestone, cold steel, weathered timber, damp earth,
oxidised copper, wet rock — held at restrained saturation so nothing shouts.
Graded like a cinema feature: shadows carry a cool navy tint while highlights stay warm and clean,
strong contrast, fine filmic texture. **The scene keeps its own natural light** — a sunlit noon
courtyard stays bright and open, an overcast morning stays soft, a night storm stays dark.
Never force gloom onto a scene that should be lit, never a flat blue wash,
never a studio backdrop, never a plinth or display stand.
Photoreal-leaning 3D with clean readable forms and crisp surface detail.
Immersive, precise, expensive-looking. If any cool cyan light appears in the scene itself
(a lamp, a reflection), keep it subtle — the frame stays clean unless an annotation,
or a holographic reconstruction described in the SUBJECT, is explicitly asked for.""",
    # ⑩ blueprint — 1분공구리류 설계 도해. 다크 네이비 + 백색 선화 + 네온 하이라이트 하나
    # ⑮ claysection — 정통 CAD·엔지니어링 단면 룩. 재질을 통째로 죽이는 게 핵심이다:
    #    색과 질감이 사라지면 남는 정보가 '형상과 치수'뿐이라 구조가 그냥 읽힌다.
    #    잘린 면을 한 톤 진하게 채우는 건 건축 도면의 poché 관습 그대로다.
    "claysection": """Style: rendered as a clean engineering study model in uniform matte clay —
the entire object is one single neutral light-grey material with no colour, no texture,
no wood grain, no stone speckle, no rust, no dirt. Soft even studio light from above with gentle
ambient shading in the crevices, sitting on a plain pale seamless background with a soft contact
shadow. Every edge crisp and precise, like a CAD model or a 3D-printed sectioned display piece.
Where the object is cut open, the cut faces are filled a clear step darker than the outer
surfaces so the thickness of every wall, floor and slab reads instantly.
Nothing shiny, nothing atmospheric, no environment, no props — only the form and its geometry.""",
    # ⑯ planline — 실사 위가 아니라 '도면 그 자체'. blueprint(네이비 청사진)와 나누는 기준은
    #    배경과 용도다: blueprint 는 설계 도해, planline 은 공간 배치·동선을 위에서 읽는 평면도.
    "planline": """Style: rendered as an architectural plan drawing — thin luminous white line-work
on a deep near-black background, seen straight from above with no perspective.
Walls are drawn as clean double lines, openings and stairs marked with simple standard symbols,
and the cut walls filled solid so the plan reads at a glance. Line weights vary the way a real
drawing does: heavier for cut walls, lighter for what lies beyond.
Precise, calm and geometric — no shading, no materials, no photographic texture, no perspective
depth, and NO readable text, numbers or labels.""",
    "blueprint": """Style: rendered as a technical blueprint diagram on a dark navy drafting board.
Clean white line-work with precise dimension lines and hatching, one or two elements
highlighted with a single glowing neon accent (cyan or red).
Flat orthographic or simple section view, engineering-drawing aesthetic,
but NO readable text, numbers or labels. Minimal, precise, analytical.""",
    # ⑪ aerial — 실사 드론 항공. arch3d(3D 렌더 전경)와 달리 '진짜 항공 촬영' 룩
    "aerial": """Style: rendered as real aerial drone photography shot from high above
on a full-frame camera. Photorealistic city, terrain or infrastructure seen from the air,
natural atmospheric haze and sunlight, crisp detail, documentary realism —
looks like actual drone footage, not a 3D render.""",
    # ⑫ xsection — 단면 실험. 핵심은 '속이 보이는 것'이지 수조가 아니다.
    # 잘린 단면·투명 벽·반으로 가른 모형 중 장면에 맞는 방법을 모델이 고르게 둔다.
    "xsection": """Style: rendered as a real tabletop demonstration where the subject is opened up
so the inside is visible — sliced clean through, cut in half, or held against a transparent wall,
whichever suits it. Internal layers, channels and structure exposed at eye level.
Built from real physical materials in a bright studio: clean neutral background,
soft even lighting, tack-sharp macro detail, shallow but readable depth.
Looks like practical-effects science footage, not CG.""",
    # ⑨ labmacro — 실험 쇼츠 실사 룩 (레퍼런스: 갈륨·우라늄 등 테이블탑 실험 채널).
    # 어두운 무채색 테이블 + 검은 니트릴 장갑 + 고정 매크로. 카메라는 안 움직이고 피사체가 변한다.
    "labmacro": """Style: rendered as real macro footage from a tabletop science-experiment video.
Locked-off macro close-up on a dark neutral-grey studio table, the subject isolated
against a near-black seamless background. Soft, even studio lighting with crisp
specular highlights on metal and glass, deep depth of field, everything tack sharp.
When hands appear they wear black nitrile gloves. Real lab props only —
petri dishes, beakers, tweezers, measuring instruments.
Clean, clinical, hyper-real — like footage from a high-end mirrorless camera,
no CG look, no stylization.""",
    # ⑧ sci3d — 3D 과학/메디컬 시각화. diagram(플랫)과 render3d(제품)의 중간.
    # "인포그래픽처럼 명확하되 질감은 실사"가 핵심 — 이 채널의 원리 컷에 가장 강하다.
    "sci3d": """Style: rendered as a photorealistic 3D scientific visualization,
in a modern real-time engine (Unreal Engine 5 / Octane look).
Highly detailed photoreal materials with visible micro-surface texture,
subsurface scattering where appropriate, cinematic studio lighting with a soft key
and subtle rim light, gentle atmospheric depth, clean neutral or soft gradient backdrop.
Infographic clarity — whatever is shown reads instantly — but with real material response,
not flat vector shapes.""",
    # ⑨ tech3d — 다큐 explainer 3D. 레퍼런스 영상 역추적으로 도출.
    # 공식: 무채색 청회색 바탕 + 「보이지 않는 것」에만 채도 높은 발광색 하나(열=주황, 구조·흐름=청록).
    # 저폴리로 살짝 단순화해 가독성을 올린다. 치수선·라벨은 편집에서 얹으므로 넣지 않는다.
    "tech3d": """Style: rendered as a stylized 3D engineering visualization,
like a modern documentary explainer shot.
Desaturated blue-grey grade — every material in the scene pushed toward muted greys,
set against a dark background.
ONE saturated emissive accent color marks the thing being explained
(glowing orange for heat, cyan or blue for flow, red for the point of interest),
with a soft bloom around it. Everything else stays desaturated so the accent reads instantly.
Slightly simplified low-poly geometry with clean visible facets — graphic and readable, not photoreal.
Strong key light with deep shadows and high contrast, generous empty space around the subject
so captions can be added later in editing.""",
    # ⑩ arch3d — 주광 건축 시각화. tech3d(암전+발광)와 짝을 이루는 '전경/건설 장면' 톤.
    # 같은 영상 안에서 도입·마무리 establishing shot에 쓰인다.
    "arch3d": """Style: rendered as a clean architectural-visualization image in soft natural daylight.
Realistic but slightly idealized materials, soft overcast or early-morning light,
gentle ambient occlusion, no harsh shadows, calm desaturated grade with one cool accent tone.
Tidy, orderly and easy to read — the polished look of a professional presentation render
rather than a photograph. Neutral, even lighting across the whole frame.""",
}
STYLE_LABELS = {"docu3d": "다큐 3D (브랜드)", "tech3d": "3D 설명", "sci3d": "3D 실사",
                "arch3d": "3D 전경", "snap": "폰카 스냅샷", "cine": "시네마틱",
                "archive": "옛날 사진 (빈티지 흑백)", "illust": "일러스트",
                "labmacro": "실험 매크로", "xsection": "단면 실험",
                "claysection": "클레이 단면 (CAD 룩)", "planline": "평면 선화 (도면)",
                "aerial": "실사 항공 (드론)", "blueprint": "청사진 도해",
                "game": "게임 렌더 (인물 OK)", "anime": "만화 요약 (인물 OK)",
                "story3d": "이야기 3D (인물 OK)", "toy3d": "피규어 3D (인물 OK)",
                "tabletop": "미니어처 3D", "blackstage": "심플 블랙 (검은 무대)",
                "greycast": "회색 마네킹 (얼굴 없음)", "whitecast": "흰 모형 (얼굴 없음)"}
# 톤 UI 그룹 (프론트 select optgroup 순서) — 3D가 이 채널의 주력이라 맨 위.
# STYLE_DEFAULTS 의 모든 톤이 여기 등장해야 편집 UI에 노출된다 (2026-08-06)
STYLE_GROUPS = [("3D (주력)", ["docu3d", "tech3d", "sci3d", "arch3d"]),
                ("실사", ["snap", "cine", "archive", "aerial"]),
                ("실험·단면", ["labmacro", "xsection", "claysection", "tabletop", "blackstage"]),
                ("인물 3D", ["game", "story3d", "toy3d", "greycast", "whitecast"]),
                ("그래픽", ["anime", "illust", "blueprint", "planline"])]
# 자료 화면 계열 톤 — 구조가 명확해서 카메라가 움직이면 요소 개수가 바뀌는 사고가 난다.
# (실측 2026-08-13: 미니어처 설원 컷을 느린 돌리로 뽑았더니 스키어가 5명→2명→7명이 되고
#  없던 안개가 생겼다) → _auto_camera 가 이 톤들의 카메라를 묶는다.
SOURCE_STYLES = {"collage", "mapboard", "vector", "productshot", "chalkboard", "xray", "tabletop"}
# 구버전 톤 → 대체 톤. 예전 config·컷 데이터가 남아 있어도 조용히 깨지지 않게 한다.
STYLE_MIGRATE = {"macro": "sci3d", "diagram": "tech3d", "render3d": "sci3d",
                 "aqua": "xsection"}   # 수조 한정 → 단면 일반으로 확장 (2026-08-06)


def norm_style(s, default="snap"):
    s = STYLE_MIGRATE.get(s, s)
    return s if s in STYLE_DEFAULTS else default

SUBJECT_LOCK = ("The style above controls only how the image looks — lighting, materials, grade "
                "and level of realism. It must not change WHAT is shown. Render exactly the "
                "SUBJECT described at the top; never substitute a different scene, location, "
                "structure or object.")

# 얼굴 정책 두 벌 — 기본은 익명(숨김), game 톤만 스타일라이즈드 얼굴 허용.
# _build_prompt 가 game 컷에서 FACE_HIDE → FACE_GAME 으로 갈아끼운다.
FACE_HIDE = """People may appear, but never show a recognizable face. Keep faces out of frame,
turned away, in shadow, backlit, or hidden behind what they are holding or doing —
show hands, arms, backs and silhouettes instead. Anonymous and a little mysterious,
never a posed portrait."""
FACE_GAME = """People may appear with visible, expressive faces — clearly stylized game
characters, close-ups allowed. Invent an original face every time;
never resemble any real, famous, or public person, living or dead."""
# 만화 요약 톤 — 얼굴이 정체성인 톤이라 FACE_HIDE 를 풀되, 여기는 2차 창작이라
# **원작 그림체·캐릭터 디자인을 베끼지 않는다**는 잠금이 얼굴 허용보다 중요하다.
# (유니폼 번호·엠블럼·로고가 새어들어가면 그 자체로 원작 트레이드 드레스가 된다)
# 마네킹 톤 — 얼굴 자체가 없으므로 FACE_HIDE(얼굴을 프레임 밖으로·돌려서·그림자로)를 그대로
# 걸면 정면 구도를 피해버린다. 정면으로 서 있어도 되고, 대신 **닮을 얼굴이 없다**.
FACE_MANNEQUIN = """Figures may face the camera directly and stand in full view. Their heads are
blank and featureless — no eyes, nose, mouth, hair or expression to render — so no recognizable
face ever appears and no real person can be resembled."""
FACE_ANIME = """Characters appear with visible cartoon faces — round, simple and expressive,
close-ups allowed. Invent original characters every time: never resemble any real person,
and never reproduce the character designs, faces, hairstyles, costumes, team uniforms,
emblems or logos of any existing manga, anime, game or film. Clothing and props carry no
lettering, numbers, emblems or brand marks of any kind."""
NEGATIVE_CORE = """Avoid: any text, letters, numbers, captions, subtitles, watermarks,
logos, brand names, model names, readable signage.
Avoid: real existing product designs, recognizable commercial products.
Avoid: extra fingers, deformed hands, duplicated limbs, warped objects.
Avoid: resemblance to any real, famous, or public person.
""" + FACE_HIDE
# 주석(annotation) 모드에서는 텍스트 금지 줄만 갈아끼운다 — 나머지 금지(손가락·얼굴 등)는 유지
NEGATIVE_CORE_ANNO_SHAPE = NEGATIVE_CORE.replace(
    "Avoid: any text, letters, numbers, captions, subtitles, watermarks,\nlogos, brand names, model names, readable signage.",
    "Avoid: paragraphs of text, captions, subtitles, watermarks, logos, brand names.\n"
    "The technical annotation MARKS described above are wanted, but they must be pure shapes — "
    "no letters, no numbers, no words anywhere.")
NEGATIVE_CORE_ANNO_FULL = NEGATIVE_CORE.replace(
    "Avoid: any text, letters, numbers, captions, subtitles, watermarks,\nlogos, brand names, model names, readable signage.",
    "Avoid: subtitles, watermarks, logos, brand names, paragraphs of prose.\n"
    "Short annotation labels and numbers are wanted (see style) — render them crisply.")

# 홀로그램 계측 HUD 레이어. 이미지에 구울 수도, 영상에서 그려지게 할 수도 있다
# (기본은 이미지 깨끗 + 영상에서 draw — docs/브랜드톤_다큐3D.md 참고).
# 강조색 — 시안(#22D3EE)이 채널 브랜드색이고, 3D·단면 계열은 전부 시안으로 모은다.
# 빨강은 실사(snap·cine·archive·illust)의 경고·측정용 폴백이다.
# 색은 **색만** 말한다 — 질감(유리·리본·발광)은 도구별 템플릿이 정한다 (2026-08-12).
# 예전엔 cyan 에 "with a soft neon bloom" 이 붙어 있어 문장이 깨졌다:
#   "The bold glowing cyan (#22D3EE) with a soft neon bloom arrow already in the frame..."
ANNO_COLORS = {
    "red": ("bright red (#FF2D2D)", "빨강 — 실사·경고·측정 (기본)"),
    "cyan": ("bright cyan (#22D3EE)", "시안 네온 — 어두운 3D·다큐 톤"),
    "amber": ("warm amber (#FBBF24)", "앰버 — 열·에너지·주의"),
    "lime": ("electric lime (#A3E635)", "라임 — 화학·생물·성장"),
    "white": ("clean white", "화이트 — 청사진·도면"),
}
# 톤별 기본 강조색 (사용자가 '자동'을 고르면 이 표를 따른다)
# 시안(#22D3EE)이 채널 브랜드 색이라 3D·단면 계열은 모두 시안으로 모은다 (2026-08-06)
ANNO_COLOR_BY_STYLE = {"docu3d": "cyan", "tech3d": "cyan", "sci3d": "cyan",
                       "arch3d": "cyan", "xsection": "cyan", "aerial": "cyan",
                       "blueprint": "white", "labmacro": "amber",
                       # 무채색 클레이 위에서는 빨강이 가장 잘 읽힌다 (엔지니어링 도면 관습)
                       "claysection": "red", "planline": "white",
                       # 검은 무대는 톤 자체가 시안 발광을 갖고 있다 — 주석도 같은 시안으로 통일
                       "blackstage": "cyan",
                       # 마네킹 계열도 브랜드 시안으로 통일한다 (2026-08-15 결정).
                       # 원래 greycast=흰선 / whitecast=빨강이었으나, 전역 설정이 시안이라
                       # 그 값이 한 번도 쓰인 적이 없었고 — 즉 '자동'으로 되돌리는 순간
                       # 이 두 톤만 갑자기 색이 튀는 함정이었다. 실측 샘플에서도 흰 세계
                       # 위의 시안이 충분히 읽혔다(2K 3장). 검정 배경이 기본이 되면서
                       # 흰 선이 묻힐 걱정도 사라졌다.
                       "greycast": "cyan", "whitecast": "cyan",
                       # 빈티지 흑백 사진에 빨강 네온을 얹으면 톤이 통째로 깨진다 —
                       # 다큐가 옛 사진을 짚을 때 쓰는 흰 선이 맞다 (2026-08-11)
                       "archive": "white",
                       # 플랫 벡터 그림에 네온 빨강은 과하다. 흰 선이 화면과 덜 싸운다
                       "illust": "white"}

# 강조 종류 — 레퍼런스 채널 47컷 실측(2026-08-11)으로 뽑은 도구 상자.
# 예전엔 hud(윤곽선) 하나뿐이라 "이걸 보세요"만 할 수 있었는데, 레퍼런스는 강조로
# **문장의 논리를 그린다**: "물이 차오릅니다"→상승 화살표, "그쪽은 안 됩니다"→X,
# "이 구역이 문제입니다"→영역 테두리. 그래서 종류를 컷 내용에 맞춰 고르는 게 핵심이다.
#   arrow  경로·흐름·상승·이동 (레퍼런스 47컷 중 14컷 — 가장 많이 쓴다)
#   reject 기각·실패·금지 (8컷) — constraint·despair 비트와 짝이 맞는다
#   zone   영역·구역·범위를 통째로 (12컷)
#   hud    치수·계측 (8컷) — 수치가 있으면 여기로 온다
#   glow   구조물 전체 점등 (전경·항공)
#   manga  만화 기호 (anime 톤 전용)
def same_place(a, b):
    """두 컷이 같은 공간인가 — 이어붙일 때 '걸어서 도착'이 성립하는지의 판단.

    place_en 이 같으면 확실하고, 비어 있으면 subject_en 의 명사 겹침으로 본다.
    (컷 분해의 체인 검증과 같은 기준 — 거기서는 이을지 말지를, 여기서는 어떻게
    이을지를 정한다. 다른 공간이면 물리적 이동 대신 매개를 통과시킨다.)"""
    ka = re.sub(r"[^a-z]", "", (a.get("place_en") or "").lower())[:22]
    kb = re.sub(r"[^a-z]", "", (b.get("place_en") or "").lower())[:22]
    if ka and kb:
        return ka == kb
    stop = {"the", "a", "an", "of", "in", "on", "at", "and", "with", "into", "from",
            "over", "under", "its", "it", "is", "are", "to", "for", "by", "as", "that"}
    wa = {w for w in re.findall(r"[a-z]{4,}", (a.get("subject_en") or "").lower()) if w not in stop}
    wb = {w for w in re.findall(r"[a-z]{4,}", (b.get("subject_en") or "").lower()) if w not in stop}
    return len(wa & wb) >= 2


ANNO_KINDS = {"measure", "outline", "glow", "manga", "arrow", "reject", "zone",
              "flow", "void", "route", "gauge", "scale", "marker", "crack", "bracket",
              "spotlight", "count", "versus", "extent", "graph",
              "wave", "skeleton", "loadsplit", "trajectory", "spin"}
# 'hud' 는 옛 이름 — 역할이 치수·계측이므로 measure 로 읽는다. 2026-08-18 목록에서 제거하고
# 별칭만 남겼다: 옛 컷 JSON 의 hud 는 입구(정규화·판정)에서 measure 로 바뀌어 그대로 돈다.
ANNO_ALIAS = {"hud": "measure"}
# 두 점을 잇는 도구 — from_en·to_en 이 있어야 어느 축인지 정해진다.
# 나머지(reject·zone·glow·void·outline·manga)는 한 점을 가리키므로 focus_en 하나로 충분하다.
ANNO_SPAN_KINDS = {"measure", "arrow", "flow", "route"}


def anno_kind_for_cut(cut):
    """이 컷에 쓸 강조 종류. 분해기가 정한 anno_kind 가 최우선이다 —
    대사가 무엇을 말하는지는 코드가 알 수 없고 LLM 만 안다.

    분해기가 안 정했을 때의 폴백: 수치가 있으면 hud, 와이드·전경이면 glow, 나머지는 hud.
    컷별 주석 선택(glow/shape/full)이 있으면 그게 폴백보다 우선이다.

    단 anime 톤만은 컷별 선택보다 앞선다 — 플랫 셀 그림 위의 계측 HUD·발광 오버레이는
    어떤 설정으로 고르든 이물질이라, 이 톤에서는 항상 만화 기호('manga')로 간다."""
    if norm_style(cut.get("style")) == "anime":
        return "manga"
    # 분해기(또는 사용자)가 고른 종류가 최우선 — 대사가 무엇을 말하는지는 LLM 만 안다
    k = (cut.get("anno_kind") or "").strip().lower()
    k = ANNO_ALIAS.get(k, k)     # 옛 이름(hud)이 와도 measure 로 받는다
    if k in ANNO_KINDS and k != "manga":
        return k
    forced = (cut.get("anno") or "").strip()
    if forced == "glow":
        return "glow"
    if forced in ("shape", "full"):
        return "measure"
    if (cut.get("measure_en") or "").strip():
        return "measure"
    if cut.get("shot") == "wide" or norm_style(cut.get("style")) in ("aerial", "arch3d"):
        return "glow"
    return "measure"


# ── 강조 도구 3종 (레퍼런스 47컷 실측으로 추가, 2026-08-11) ────────────────
# 공통 원칙: 하나만 그린다. 여러 개 흩뿌리면 설명이 아니라 장식이 되고 시선이 갈라진다.
# 라벨은 2K 이미지에만 굽는다 — 영상(720p)에서 새 글자를 그리게 하면 뭉개진다.

# ① arrow — 경로·흐름·상승·이동. 레퍼런스가 가장 많이 쓰는 도구다.
#    "물이 차오릅니다" "이쪽으로 돌립니다" 처럼 **움직임을 말하는 문장**을 그림으로 옮긴다.
ANNOTATION_ARROW = """A single bold {accent} arrow is drawn over the scene, showing exactly one
movement: {focus}
It is one continuous slender arrow of glowing translucent light — a bright core with a soft
halo along its whole length, the surface behind showing through it — never a thick slab,
never frosted glass, never a solid physical object floating above the scene.
Its head is broad and unmistakable.
It is laid into the scene in correct perspective so it follows the real path: it starts where
that movement starts and ends where it ends, bending along the path if the path bends, and
passing behind objects nearer to the camera so it sits inside the scene rather than pasted on top.
Only ONE arrow in the whole frame. Never a scatter of arrows, never arrows pointing at nothing,
never a row of repeated chevrons. The rest of the frame stays completely untouched.{label}"""

# ② reject — 기각·실패·금지. constraint·despair 비트와 짝이 맞는다.
#    "그렇게는 안 됩니다" "5년 만에 쓸려갔죠" 같은 컷.
ANNOTATION_REJECT = """A single large {accent} X is stamped over exactly one thing: {focus}
It is drawn as two thick crossing slabs of frosted glass, each stroke FILLED solid across its
whole width with translucent colour — a filled bar, never a hollow outline and never an empty
tube with a gap down the middle. The surface behind shows faintly through the fill, and every
edge is finished with a bright neon rim that glows — almost white where it is strongest,
bleeding a soft halo of light into the air around the mark and casting a faint reflection on
the surface beneath, so it reads as lit glass rather than flat colour.
The strokes have real thickness and clean squared ends, never a flat painted mark.
Big enough to read at a glance, sitting just above that thing in correct perspective and
covering only it.
Just the one X: nothing else in the frame is marked, and no other symbols are added.{label}"""

# ③ zone — 영역·구역·범위를 통째로. 부위 하나가 아니라 '이 구역'을 말하는 컷.
# 뻗은 것 — 화면 밖까지 이어지는 **하나의 긴 대상**을 그 길이 전체에 걸쳐 점등한다.
# glow 와 갈리는 지점: glow 는 덩어리 하나(기념물·건물)를 감싸고, extent 는 선형으로 뻗은
# 것(울타리·담·터널·도로·배관·철로)이 **계속 이어진다**는 사실 자체를 보여준다.
# 근거(레퍼런스 실측 2026-08-15): 울타리 설명 컷에서 기둥 하나하나를 같은 발광 블록으로
# 세워 길이를 읽게 했다. glow 로 하면 "기둥 한 개"가 되고, count 로 하면 점만 찍혀
# 길이가 안 읽히며, zone 은 바닥 영역을 두를 뿐 서 있는 구조가 안 보인다.
ANNOTATION_EXTENT = """A {accent} luminous overlay marks one continuous run of structure: {focus}
It follows that thing along its whole length, all the way to where it leaves the frame, so the
point being made is how far it goes. Where the run is built from repeating parts — posts, panels,
sleepers, segments — every one of them lights up as the SAME simple glowing block, identical in
width and height, standing exactly where the real part stands and shrinking with perspective as
the run recedes. The blocks are translucent and softly luminous, brightest at their top edge and
fading toward the ground, and they never hide the structure they sit on.
It marks only that one run — never a second line, never the ground between, never neighbouring
buildings or objects. The rest of the frame stays completely untouched and natural.
Pure light only — absolutely no letters, digits or words."""

ANNOTATION_ZONE = """A {accent} outline encloses exactly one region: {focus}
It is a single closed boundary that follows that region's own real edges in correct
perspective — its actual outline, whether curved, round or irregular. Only when the region has
no clear edge of its own is it drawn as a clean rectangle instead.
The boundary is a thin bright line with a soft bloom. A soft halo of the same colour glows
inward from the boundary, and the whole area inside is filled with a clearly visible
translucent tint of that colour — strong enough that the region reads as one solid block at a
glance on a phone, while everything beneath the tint stays recognisable through it.
It marks the whole region at once and does not trace small details inside it.
Only one region is marked; the rest of the frame stays untouched.{label}"""

# ④ flow — 힘·하중·물·공기·열·전기처럼 **눈에 안 보이는 흐름**. arrow 와 갈라지는 기준:
#    arrow 는 방향 하나("이쪽으로 돌립니다"), flow 는 출발-경로-도착의 여정 전체
#    ("지붕 하중이 기둥을 타고 기초까지 내려갑니다").
#    굵은 띠로 굽는 게 핵심 — 가는 선은 720p 영상에서 뭉개지고, 여러 가닥으로 그리면
#    시선이 갈라져 '어디서 어디로'가 안 읽힌다 (헤어라인 HUD 실측과 같은 계열).
#    재질은 반투명 발광 — 불투명 입체 리본으로 시켰더니 만화 화살표처럼 나왔다
#    (2026-08-18 사용자 피드백). 굵기는 유지하고 재질만 빛의 띠로.
ANNOTATION_FLOW = """A single broad {accent} band runs through the scene, showing exactly one
continuous flow: {focus}
It is laid into the scene in correct perspective, hugging the real physical route: it begins
exactly where that flow starts, follows the actual path through the structure, and ends exactly
where the flow ends — widening, narrowing or bending wherever the real route does, and glowing
a little brighter at the one point where it acts on the structure.
It is rendered as a broad translucent ribbon of glowing light — soft luminous edges with a
brighter core running along its centre — shading from dim where the flow begins to bright where
it acts. It reads as light travelling through the scene, never as a solid painted object: no
opaque plastic material, no cartoon arrow, no big triangular arrowhead. If the destination
needs marking, it is a subtle brightening and slight widening where the flow ends, nothing more.
It is ONE broad continuous band, thick enough to read instantly on a phone — never a hairline,
never a bundle of thin streamlines, never a row of repeated arrows or chevrons, and never
branching into side paths. Only this one flow is drawn; the rest of the frame stays completely
untouched.{label}"""

# ⑤ void — **비어 있는 공간**을 부피로 보여준다. glow 와 결정적으로 다르다: glow 는 물체
#    표면에 달라붙지만("clings to that thing's surface"), 방·통로·빈 틈에는 붙을 표면이 없다.
#    피라미드의 널방, 성벽 안의 통로, 방 안의 공기처럼 '없는 것이 주인공'인 컷 전용.
ANNOTATION_VOID = """A translucent {accent} volume fills exactly one empty space: {focus}
It fills that hollow completely, from wall to wall and floor to ceiling, so the shape of the
empty space itself becomes visible as a solid block of soft light — brighter along the edges
where it meets the surrounding material, fainter through the middle. It reads as air made
visible, not as an object placed inside.
It stops exactly at the real surfaces that enclose it and never leaks out through them into the
surrounding stone, ground or sky. The material around it stays completely opaque and untouched —
this is the void being shown, not the walls turning transparent.
Only this one empty space is filled; every other cavity in the frame stays dark and unmarked.{label}"""

# ⑥ route — 사람·물건이 **지나간 길**. flow(물리적 흐름)와 나누는 기준은 '무엇이 지나가는가'다:
#    힘·물·공기·열이면 flow, 사람·시신·행렬·방문객이면 route. 문화유산 서사의 단골이다
#    ("왕의 시신은 이 통로로 들어갔습니다").
ANNOTATION_ROUTE = """A single {accent} route line is drawn through the space, tracing exactly one
path that people or objects took: {focus}
It runs along the floor and through the openings in correct perspective, following the way a
body would actually move — turning where the passage turns, rising where it climbs, passing
through doorways rather than through walls. It is a rounded ribbon with real thickness and a
soft bevel, shading from dim at the start to bright at the end, with a subtle shadow beneath so
it rests in the space rather than floating flat over it — marked with a small solid dot where
the path begins and a slightly larger one where it ends.
Only ONE route is drawn. Never a network of paths, never branching alternatives, never repeated
arrows along it, and it never cuts through solid material.{label}"""

# 라벨 절 — 대상을 짧은 영문 이름으로 짚는다 (레퍼런스: Steel Lid · Trench · Dry Floor …).
# **2K 이미지에서만** 쓴다. 한글은 AI 가 뭉개므로 영문 대문자 시작 1~2단어로 제한한다.
# 두 끝점 — 치수선·화살표·흐름·동선이 '어디서 어디까지'인지. 이게 없으면 모델이 축을 찍는다.
# 강조 문구 끝에 붙여 대상 서술을 구체화한다 (2026-08-12 실측으로 도입).
ANNOTATION_SPAN = ("""
It runs from {a} to {b}, touching both ends of what it marks — laid into the scene in correct
perspective along that real path, never floating in mid-air and never stopping short.""")

# ── 신규 강조 5종 (레퍼런스 254프레임 실측으로 추가, 2026-08-12) ──────────────
# gauge   세로 막대 + 눈금 + % + ✓        아파트편 창틀 60% · 피라미드편 40/200/283%
# scale   흰 실루엣을 실물 옆에 겹침        피라미드편 80톤 = 트럭 3대
# marker  여러 지점을 동시에 표시           열교환기 코일 위 점들 · 아파트 세대별 점
# crack   균열을 따라 그은 선               피라미드편 천장 균열
# bracket 모서리 브래킷으로 영역 지정        피라미드편 ⌐ NO ENTRY ¬
ANNOTATION_GAUGE = """A single vertical gauge bar stands beside the subject in {accent},
reading exactly ONE quantity: {focus}
It is a slim upright track with fine graduation ticks along one side, filled from the bottom
up to the level that represents the value, the filled part solid and the rest left empty.
The reading "{m}" sits at the top of the fill in the same colour, in a small clean sans-serif.
It stands clear of the subject against empty background — never laid across it, never repeated,
and never more than one gauge in the frame. Nothing else in the scene is marked."""

# ── 신도구 4종 (2026-08-18 시제품 검증 후 등록) — 주제 커버리지 갭에서 나왔다:
#   wave=퍼지는 것(충격파·폭발·음파·확산) · skeleton=숨은 부재망(리브·혈관·신경·트러스)
#   loadsplit=갈라지는 힘(아치·삼각공간) · trajectory=공중 포물선(탄도·투척)
#   문구는 전부 시제품에서 그대로 성립한 것 — 고치려면 다시 뽑아 확인하라.
# spin — 회전 표시 (2026-08-18 시제품 검증). 이름을 orbit 로 하지 않은 이유:
#   ① 카메라 프리셋 orbit 과 분해기가 혼동한다 ② 'orbit' 단어는 행성/궤도 환각 위험.
#   시제품에서 나선이 2~3회 감기며 나왔고 그게 회전 표현으로 더 좋아 문구를 그에 맞췄다.
ANNOTATION_SPIN = """A single {accent} rotation indicator is drawn around exactly ONE spinning part: {focus}
A thin luminous helical sweep of two or three tight turns wraps around the part's real rotation
axis, hugging the surface at a constant radius, locked to the part in correct perspective and
passing behind it where the geometry demands. A clear arrowhead at the sweep's end shows the
direction of rotation, and a small glowing dot marks where the sweep begins.
Only this ONE sweep in the whole frame — never separate concentric rings, never a flat 2D icon,
and nothing resembling planets or orbits in space.
The rest of the image stays completely untouched.
Pure light only — absolutely no letters, digits or words."""

ANNOTATION_WAVE = """Expanding {accent} wavefronts radiate from exactly ONE origin: {focus}
Three or four thin concentric rings — no more — spread outward from that origin, spaced wider
as they travel, each ring locked to the scene in correct perspective: flattening into ellipses
where they cross the ground, tilting with the surfaces they pass over. The rings are thin
luminous lines with a soft bloom, brightest nearest the origin and fading as they expand.
A small glowing dot marks the origin itself.
They mark only that one event — never a second origin, never rings scattered elsewhere.
The rest of the frame stays completely untouched.
Pure light only — absolutely no letters, digits or words."""

ANNOTATION_SKELETON = """A {accent} network of hidden internal members is drawn onto the subject itself,
revealing the structure that does the real work: {focus}
Thin luminous lines trace each member along its true position — following the subject's own
form in correct perspective, bending where it bends, passing behind parts nearer to the camera
so the network reads as INSIDE the subject, never painted flat on top. Members that repeat
(ribs, vessels, struts) are drawn in the same weight and style so they read as one system.
The subject stays fully visible through the network — the overlay is translucent light, never
a solid diagram replacing the surface.
Only this one network in the whole frame. The rest of the image stays completely untouched.
Pure light only — absolutely no letters, digits or words."""

ANNOTATION_LOADSPLIT = """A single {accent} force path is drawn into the structure, showing how ONE load
divides and travels around instead of through: {focus}
It begins as one luminous stream where the load enters, descends a short way, then splits
cleanly into TWO branches that follow the structure's real load-bearing members — down one
side and down the other — each branch ending in a clear arrowhead where the load reaches the
ground. The region the load avoids stays completely clean: no line, no glow, nothing passes
through it. Drawn as thin bright strokes locked to the structure in correct perspective,
brightest at the split. Only this one path in the whole frame — never a third branch, never
arrows pointing back upward. The rest of the image stays completely untouched.
Pure light only — absolutely no letters, digits or words."""

ANNOTATION_TRAJECTORY = """A single {accent} flight arc is drawn through the air, tracing exactly ONE
trajectory: {focus}
It rises from the launch point, curves over its highest point, and descends to the impact
point in one smooth continuous parabola — a thin luminous line hanging in the air in correct
perspective, receding into the scene, never pasted flat on the screen. A small glowing dot
marks the launch point, a clear arrowhead sits at the impact end, and a faint ring on the
ground marks where it lands.
Only this ONE arc in the whole frame — never a bundle of arcs, never a second impact.
The rest of the image stays completely untouched.
Pure light only — absolutely no letters, digits or words."""

# 곡선 그래프 — 정량 관계("깊을수록·길수록·갈수록")를 구조물 위에 선으로 그린다.
# 2026-08-18 실측(댐 수압): 축+눈금+곡선+옅은 워시 구성이 글자 없이 "깊을수록 강하다"를
# 읽히게 했다. 레퍼런스 채널의 압력·속도 곡선(티거 88mm 편)이 이 도구의 원형이다.
ANNOTATION_GRAPH = """A thin {accent} analytic curve is drawn onto the structure itself, showing how
ONE quantity varies along it: {focus}
A slim axis line hugs the structure along the direction of change, with fine graduation ticks.
From it a smooth thin curve bows away — closest to the axis where the value is smallest and
furthest where it is greatest — so the widening gap between axis and curve IS the message.
The area between axis and curve carries a very faint translucent {accent} wash, denser where the
value is greater. A small glowing dot pins each end of the axis to the structure.
Every line is locked to the structure in correct perspective, thin and crisp like a
light-emitting instrument overlay — never a flat sticker pasted on top.
Only this ONE graph in the whole frame — never a second curve, never a legend, never a frame or
panel around it. The rest of the image stays completely untouched.
Pure marks only — absolutely no letters, digits or words."""

ANNOTATION_SCALE = """A familiar object is drawn beside the subject purely for scale: {compare}
It is rendered in {accent}: a bold outline of that colour with a faint translucent fill of the
same colour — heavy enough that the shape reads instantly from across the room, the way a scale
figure is drawn on an architectural board, never a thin delicate sketch line and never plain white.
It stands on the same ground plane at the correct relative size, right next to the subject and
close to it, filling a clear share of the frame so the two can be compared without effort.
If several are needed, they line up in a neat row, evenly spaced and all the same size.
The subject itself stays completely untouched — the outline never overlaps or hides it.{label}"""

# 분할 비교 — 널리 알려진 모습과 실제 모습을 한 화면에 세운다. 다른 도구가 한 장면 위에
# 그래픽을 얹는 것과 달리 이건 **화면 자체를 가르는 레이아웃**이라 성격이 다르다.
#
# 좌우가 아니라 위아래로 가른다. 9:16 세로 화면을 좌우로 나누면 한 면이 4.5:16 이 되어
# 건물도 사람도 안 들어간다. 위아래면 각 면이 9:8 — 거의 정사각형이라 둘 다 읽힌다.
# 위가 '알려진 것', 아래가 '실제' — 시선이 위에서 아래로 흐르는 순서와 반전이 맞물린다.
ANNOTATION_VERSUS = """The frame is split into two stacked panels of equal height, one above the
other. **The two panels meet edge to edge with nothing between them** — no line, rule, bar, stripe,
border, gap, margin, shadow or seam of any kind, in any colour. The pictures themselves are what
separate the halves: the moment the content changes is the boundary.
The TOP panel shows the widely known, expected version: {compare}
The BOTTOM panel shows what is actually there: {focus}
Both panels are the same scene rendered in exactly the same style, lighting, palette, camera
height and lens — the only difference between them is the thing being compared. They are two
views of one subject, never two different photographs collaged together.
The same part of the subject sits at the same position in both panels, so the eye can jump
straight down from one to the other and see the difference without hunting for it.
Nothing crosses from one panel into the other, and neither panel is tinted, faded or dimmed.
No text anywhere: no labels, captions, headings, boxes, badges, letters, numbers or watermarks in
either panel. The difference between the two panels is the whole message and it has to read
without a single word.{label}"""

ANNOTATION_MARKER = """Small {accent} dots mark every point where this happens: {focus}
Each is the same small filled circle with a faint glow, sitting exactly on the surface in
correct perspective, following the real geometry as it recedes. They mark only the points
described above — never scattered at random, never on empty ground, never joined by lines,
and never varying in size or shape.
Nothing else in the frame is marked, and there is no text.{label}"""

ANNOTATION_CRACK = """A single {accent} line traces one real crack in the material: {focus}
It follows the actual fracture exactly as it runs across the surface — branching only where the
crack itself branches, thinning where it closes, and stopping where it stops. It sits on the
surface in correct perspective, never floating above it.
The line itself stays fine, but a narrow halo of the same colour bleeds softly outward along
its whole length — like light seeping out of the fissure — so the crack reads instantly even
on a small phone screen.
Only this one crack is traced; every other flaw, joint and mortar line in the frame stays
unmarked. No text.{label}"""

# 스포트라이트 — 선으로 감싸는 대신 **빛으로 골라낸다**. 대상이 작거나 배경이 복잡해
# 윤곽선이 안 읽히는 자리(군중 속 한 사람, 부품 더미 속 하나)에 쓴다.
ANNOTATION_SPOTLIGHT = """Exactly one thing in the scene stays fully lit while everything else
darkens around it: {focus}
A soft pool of {accent}-tinted light falls on that one thing, keeping its own colour and detail
crisp, and fades outward into the surroundings. Everything outside that pool is dimmed and
desaturated — still visible and still recognisable, never blacked out or blurred away, just
clearly pushed back so the eye lands on the lit thing first.
The edge of the pool is soft, following the shape of what it picks out rather than a hard
circle stamped on the picture. Only ONE thing is lit; there is no second pool anywhere.{label}"""

# 개수 — 여러 지점을 찍고 **총계를 함께** 보여준다 (레퍼런스: 세대별 붉은 점 + 30세대).
ANNOTATION_COUNT = """Every one of them is marked with the same small {accent} dot: {focus}
Each dot is identical in size and shape, sitting exactly on its target in correct perspective,
following the real geometry as it recedes — never scattered at random and never joined by lines.
A single running total reading "{m}" sits clear of the group in the same colour, in a bold clean
sans-serif, so the count reads at a glance without anyone having to count the dots.
Nothing else in the frame is marked, and that total is the ONLY text.{label}"""

ANNOTATION_BRACKET = """Four {accent} corner brackets frame exactly one area: {focus}
They are short right-angle marks at the four corners of that area — the corners only, never a
closed rectangle, never a filled box. They sit flat on the screen like a targeting overlay,
sized so the area inside stays fully visible and unobstructed.
Only ONE set of brackets in the frame, and nothing inside them is covered or tinted.{label}"""

# 수치 — 치수선 말고 화살표·흐름·동선에도 값이 붙을 때가 있다 (레퍼런스: 운반 경로에 800Km).
# 라벨과 달리 '그 선의 값'이므로 선과 같은 색으로 작게 놓는다.
ANNOTATION_VALUE = ("""
The value "{m}" sits beside it in the same colour as the mark, in a small clean sans-serif
sized to match the line weight — never a white caption laid over the picture, never repeated.""")

# 라벨 — 레퍼런스는 굵은 산세리프 대문자를 쓴다 (Five Voids · NO ENTRY · LOAD DISTRIBUTION).
# 색을 안 정해 두면 모델이 흰 큰 글씨를 얹어 자막처럼 보인다 (2026-08-12 제보).
# 라벨 — 레퍼런스는 굵은 산세리프 대문자를 **색 박스 안에** 넣는다 (Emptied Void 2 · 앞마당).
# 배경 없이 글자만 얹으면 돌·하늘 위에서 대비가 무너지고 자막처럼 읽힌다.
# 짧은 지시선으로 대상과 이어 두면 어디에 붙은 라벨인지 분명해진다.
ANNOTATION_LABEL = ("""
A short label sits beside it, and the label reads exactly this and nothing more: "{label}"
Those characters are the entire label — do not add any other word to it.
It is set in a bold clean upper-case sans-serif in a dark ink colour, inside a small solid block
of the same colour as the mark — a filled tag, not loose floating text — with a short thin
leader line joining the tag to what it names.
It is sized to read as an engineering callout rather than a caption, and it never covers the
thing it labels. That word is the ONLY text in the frame — never repeat it, never add other
words, numbers or captions.""")


# 오브젝트 하이라이트 — HUD(선)와 다른 제2의 강조: 대상 전체를 반투명 발광으로 채운다.
# 모서리·능선은 더 밝게, 꼭대기엔 작은 플레어. 다큐 채널의 '이 구조물 얘기 중' 연출.
ANNOTATION_GLOW = """A translucent {accent} holographic overlay covers exactly one thing: {focus}
Its entire visible volume fills with a soft luminous glow — noticeably brighter along its
edges, ridgelines and silhouette, with a small bright flare at its highest point — like a
monument being highlighted in a documentary graphic. It lights up exactly the thing named
above — not simply the biggest structure in view. The overlay clings exactly to that
thing's surface in correct perspective; it never spills onto the ground, sky or
neighbouring objects. The rest of the frame stays completely untouched and natural.
Pure light only — absolutely no letters, digits or words."""

# 계측 전용 — 끝점(from_en·to_en)과 수치가 둘 다 있을 때 쓴다. 윤곽선을 그리지 않는다.
# 근거(2026-08-12 실측): 같은 골격에서 첫 문장만 "holographic HUD" → "technical dimension
# line" 으로 바꾸자 43m 가 엉뚱한 축(통로 폭·천장 경사)에 붙던 게 세 번 다 바로잡혔다.
# 'holographic / HUD / switches on' 은 모델을 SF 인터페이스 쪽으로 민다 — 우리가 원하는 건
# 인쇄된 도면이다.
ANNOTATION_MEASURE = """A technical dimension line in {accent} is drawn into the scene,
measuring exactly ONE span: {focus}
It has a clear arrowhead at each end, and a thin extension line runs out from the object's
edge to meet each arrowhead — the way a measurement is marked on an architectural or
engineering drawing.
The reading "{m}" sits ON the dimension line, breaking it at its centre — the line pauses
for the value and continues after it — in the SAME colour as the line, in a small clean
sans-serif sized to match the line weight, never a white caption laid over the picture.{span}
{exclusive}
The rest of the frame stays completely clean, and that reading is the ONLY text in the image —
never repeat it, never add other words or numbers."""
# 기본: 치수선은 한 프레임에 하나뿐이다.
MEASURE_ONLY_ONE = ("Only ONE dimension line in the whole frame. It never wraps around the "
                    "object as an outline, never repeats on other axes, and never floats free "
                    "of what it measures.")
# 도면형 톤(회색 단면·제품 도해)의 밀도판 — 레퍼런스(2026-08-19 열교환기·단면 도해)의
# 'CAD 도면 속 물건' 인상을 만든다. **값은 주 치수 하나만** — 여러 숫자를 요구하면 모델이
# 수치를 지어낸다 (그 레퍼런스도 자세히 보면 125m·12.6nm 같은 엉터리 단위다).
MEASURE_DRAFT_SET = ("Two or three secondary dimension lines accompany it, marking the "
                     "object's other principal extents — width, height or thickness — in the "
                     "same drafting style with extension lines and arrowheads, but carrying "
                     "NO value: bare measurement lines only, slightly thinner and dimmer than "
                     "the main one so the labelled measurement clearly leads. Each one lies "
                     "parallel to the edge it measures, tight against the object, and sits "
                     "entirely inside the frame — never running off the edge of the picture. "
                     "Together they read like a page from an engineering drawing. None of "
                     "them wraps the object as an outline or floats free of it.")
MEASURE_DRAFT_STYLES = {"claysection", "xsection", "sci3d", "productshot"}

# 지목 전용 — "여러 개 중 이것" 을 가리킨다. 치수가 아니라 위치를 말하는 컷.
ANNOTATION_SHAPE = """A single {accent} contour is drawn over the scene,
tracing exactly ONE thing: {focus}
It follows that thing's own outline{dim}{grid}.
The stroke is clean and thin — fine enough to read as an instrument overlay rather than paint,
but still solid and unbroken on a phone screen.
It hugs exactly the thing named above and nothing else — not the largest or most
prominent object in the frame, not the whole scene. If that thing is a part, a joint, a
layer or a detail of something bigger, the contour wraps only that part and leaves the rest
of the object bare. It never stretches across empty ground.
The contour is ONE continuous line following that thing's own edge. Never a bundle of
parallel lines, never hatching, never stripes ruled across the object's surface, and
never a rectangular frame, viewfinder box or corner brackets sitting on top of the scene —
those hide the subject instead of pointing at it.
Absolutely no thick or tapered strokes, no chunky cartoon arrows, no hand-drawn scribbles,
no marks pointing at nothing.
The rest of the frame stays completely clean.
Marks only — absolutely no letters, digits or words."""
# 실측(2026-08-06): 한글 라벨은 AI가 뭉갠다("등대 높이"→"롱대 늪이"). 숫자·영문 단위는 깨끗하게 나온다
# → 라벨 모드는 '숫자 치수만' 허용하고 한글 라벨은 편집에서 얹는 것이 품질이 일정하다.
# 만화 기호 강조 — anime 톤의 강조 문법. 계측 HUD·발광 오버레이는 이 톤에서 이물질이라
# (플랫 셀 그림 위에 홀로그램이 뜬다) 대신 그림의 일부인 집중선·충격 기호로 시선을 몬다.
# 색 지정이 없다 — 만화 기호는 그림과 같은 검은 윤곽선이라 강조색 개념이 없다.
ANNOTATION_MANGA = """Cartoon emphasis marks pull the eye to exactly one thing: {focus}
Thick hand-drawn focus lines radiate inward toward it from the edges of the frame, and a few
bold flat impact marks sit right beside it. They are drawn in the same thick dark outline and
flat color as the rest of the picture — flat shapes only, never glowing, never translucent,
never a digital overlay on top of the art. They stay clear of the characters' faces.
Marks only — absolutely no letters, digits or words."""
ANNOTATION_MODES = {"shape", "full", "auto", "glow"}   # 실제 문구는 annotation_block 이 조립한다


# 라벨 앞에 붙어도 뜻을 더하지 않는 말들 — 화면에서는 글자수만 늘린다
LABEL_STOP = {"the", "a", "an", "this", "that", "one", "its", "of", "for"}


def anno_label(cut):
    """화면에 새길 짧은 영문 라벨 (Latch · Gasket · Void · Relieving Chamber).

    한글은 AI 가 뭉갠다(실측: "등대 높이"→"롱대 늪이") → 라틴 문자만 남긴다.
    그리고 **짧을수록 안 뭉개진다** → 관사·지시어를 걷어내고 2단어·14자로 자른다.
    길어지면 모델이 글자를 흘리기 시작하고, 그러면 없느니만 못하다."""
    raw = (cut.get("anno_label") or "")
    # 분할 비교는 슬래시로 두 라벨을 받는다("KNOWN / ACTUAL"). 통째로 2단어 규칙에 넣으면
    # "KNOWN /" 이 되어 뒤쪽 라벨이 증발한다 — 양쪽을 따로 줄이고 다시 붙인다.
    if "/" in raw and (cut.get("anno_kind") or "").strip().lower() == "versus":
        a, b = raw.split("/", 1)
        a, b = anno_label({"anno_label": a}), anno_label({"anno_label": b})
        return f"{a} / {b}" if (a and b) else ""
    s = re.sub(r"[^A-Za-z0-9 %°/.\-]", "", raw).strip()
    w = [x for x in s.split() if x.lower() not in LABEL_STOP] or s.split()
    out = " ".join(w[:2])
    # 길면 단어 경계에서 줄인다 — 글자 중간을 자르면 "Relieving Cham" 처럼 뜻이 깨진다
    if len(out) > 16:
        out = w[0] if len(w[0]) <= 16 else w[0][:16]
    return out.strip()


# motion_en 끝에 세미콜론으로 붙이는 **도형 애니메이션**은 지침이 허용한 기능이다
# (게이지·스캔선·측량 그리드·비교 막대). 이건 영상 프롬프트에만 실리고 이미지에는 안 간다.
#
# 문제가 되는 건 **강조 도구와 겹칠 때 하나뿐**이다. 지침은 "이 그래픽을 붙인 컷은
# focus_en·measure_en 을 비워라 — 강조 장치는 컷당 하나"라고 했지만, 지침만으로는 재발한다
# (홀로그램·분해뷰 컷에서 같은 일이 있어 코드로 막아둔 전례가 있다).
# → anno_kind 가 살아 있는 컷에서만 이 절을 걷어낸다. 그 외에는 그대로 둔다.
#
# 도구 이름만으로 잡으면 실제 사물을 오해한다 — "marker post"(표지 기둥), "arrow slit"(화살
# 구멍)은 진짜 피사체다. 강조 색(시안·마젠타·네온)이 도형과 짝지어 나올 때만 잡는다.
GRAPHIC_MOTION_RE = re.compile(
    r"[^.;]*\b(?:"
    r"holograph\w*|annotation\w*|dimension lines?|measurement (?:line|grid|overlay)|"
    r"HUD|"                                            # 대문자 HUD 만 (hud 는 흔한 오타)
    r"(?:cyan|magenta|neon)\b[^.;]{0,40}?\b(?:bars?|lines?|arrows?|outlines?|overlays?|"
    r"markers?|dots?|bands?|rings?|brackets?|grids?|gauges?|arcs?)"   # 색 + 도형이 짝지어 나올 때만
    r")\b[^.;]*[.;]?")


def strip_graphic_motion(s, has_anno=False):
    """강조 도구가 붙은 컷에서만 motion 의 도형 애니메이션 절을 걷어낸다.
    도구가 없으면 그 절이 그 컷의 유일한 강조이므로 그대로 둔다."""
    if not s or not has_anno:
        return s
    out = GRAPHIC_MOTION_RE.sub("", s)
    out = re.sub(r"\s*;\s*;", ";", out).strip(" ;,")
    # 문장이 통째로 그래픽 지시였으면 빈 값으로 둔다 — 비면 프롬프트가 "이 장면이 자연스럽게
    # 할 수 있는 가장 눈에 띄는 변화" 기본 문구로 채우므로 정지화면이 되지 않는다.
    return out


def versus_labels(cut):
    """분할 비교는 **글자 없이** 간다 (2026-08-15 결정).

    예전엔 anno_label 을 슬래시로 갈라 위/아래에 하나씩("MYTH / REALITY") 구웠다. 접은 이유:
      · 굽힌 글자는 편집에서 못 고친다. 자막으로 얹으면 폰트·크기·타이밍을 다 통제할 수 있다
      · 라벨 상자가 화면 위쪽을 크게 잡아먹어 정작 비교할 그림이 밀렸다
      · 두 면의 차이가 그림만으로 안 읽히면 애초에 컷이 실패한 것이다 — 글자로 때울 일이 아니다
    빈 문자열을 돌려주고, '글자 금지'는 ANNOTATION_VERSUS 본문이 직접 못박는다.
    anno_label 값이 들어와도 조용히 무시한다(분해기가 옛 습관으로 채워도 안전하게).
    """
    return ""


# 흐름의 색은 **내용이 정한다** — 찬 공기와 열을 같은 색으로 그리면 설명이 성립하지 않는다.
# 레퍼런스 실측: 하늘색=시원한 공기·정상 유입, 주황=더운 공기·배출·열, 빨강(발광)=힘·하중.
# 지시·계측 계열은 브랜드색 하나로 통일하고, 여기만 예외로 둔다.
FLOW_COLORS = {
    "cold_air": "translucent pale cyan (#7DD3FC)",
    "warm_air": "translucent warm amber-orange (#FB923C)",
    "heat": "translucent warm amber-orange (#FB923C)",
    "water": "translucent blue (#38BDF8)",
    "force": "emissive red (#FF3B45) with a bright core and restrained bloom",
    "electricity": "bright yellow (#FDE047)",
    "smoke": "translucent grey-white",
    # 인체 주제용 (2026-08-18) — 피는 힘(force)의 발광 적색과 구분되는 깊은 진홍
    "blood": "translucent deep crimson (#B91C1C)",
}


def anno_accent(color, cut):
    """이 컷의 강조색 문구. 'auto' 면 톤에 어울리는 색을 고른다.

    흐름(flow) 컷에서 flow_of 가 지정돼 있으면 **그 물질의 색**이 브랜드색을 이긴다."""
    kind = ANNO_ALIAS.get((cut.get("anno_kind") or "").strip().lower(),
                          (cut.get("anno_kind") or "").strip().lower())
    if kind == "flow":
        f = (cut.get("flow_of") or "").strip().lower()
        if f in FLOW_COLORS:
            return FLOW_COLORS[f]
    c = (color or "auto").strip()
    if c == "auto" or c not in ANNO_COLORS:
        c = ANNO_COLOR_BY_STYLE.get(norm_style(cut.get("style")), "red")
    return ANNO_COLORS[c][0]


def annotation_block(mode, cut, color="auto"):
    """주석 문구 조립. **가리킬 대상(focus_en)이 없으면 주석을 아예 넣지 않는다** —
    지시가 없으면 AI가 화면을 장식으로 채워 맥락 없는 화살표가 흩뿌려진다 (실측 2026-08-06)."""
    if mode not in ANNOTATION_MODES:
        return ""
    # 컷별 선택이 '자동'인 채로 들어올 수 있다 — 여기서도 컷 성격 판정을 거치게 한다.
    # (거치지 않으면 훅·마무리 컷까지 주석이 붙어 auto 게이팅이 무력화된다)
    if mode == "auto" and not anno_for_cut("auto", cut):
        return ""
    focus = (cut.get("focus_en") or "").strip()
    if not focus:
        return ""
    # 분해기가 마침표 없이 주므로 그대로 끼우면 뒷문장과 한 덩어리로 붙는다
    # ("…lock together The interface is built…") — 모델이 문장 경계를 놓친다
    focus = focus.rstrip(" .;,") + "."
    # 만화 기호 — anime 톤. 색·수치 개념이 없다 (검은 윤곽선 도형이고 글자는 금지)
    if anno_kind_for_cut(cut) == "manga":
        return ANNOTATION_MANGA.format(focus=focus)
    # 도구 선택은 **분해기가 정한 anno_kind 만** 덮어쓴다. 여기서 폴백 판정까지 쓰면
    # 사용자가 'HUD 도형만'을 고른 와이드 컷이 제멋대로 발광으로 가버린다 (mode 무시).
    kind = (cut.get("anno_kind") or "").strip().lower()
    kind = ANNO_ALIAS.get(kind, kind)          # hud → measure (옛 이름 호환)
    if kind not in ANNO_KINDS or kind == "manga":
        kind = ""
    accent = anno_accent(color, cut)
    # 영문 라벨 — 2K 이미지에만 굽는다. shape 모드는 '글자 없음'이라 라벨도 안 넣는다
    # (영상에서 새 글자를 그리는 건 계속 금지 — 720p 에서 뭉개진다)
    label = ""
    lb = anno_label(cut)
    if lb and mode != "shape":
        label = ANNOTATION_LABEL.format(label=lb)
    # 두 점을 잇는 도구(치수선·화살표·흐름·동선)는 **끝점 두 개**가 있어야 그릴 수 있다.
    # focus 하나만 주면 모델이 어느 축인지 몰라 찍는다 — 실측(2026-08-12): 대회랑 높이를
    # 물었는데 세 번 중 한 번은 통로 '폭'에 43m 를 붙였고, 하중 화살표는 좌우로 갈라지는
    # 핵심을 못 그려 설명이 뒤집혔다. 끝점을 주면 같은 톤·같은 골격에서 전부 바로잡혔다.
    span = ""
    a, b = (cut.get("from_en") or "").strip(), (cut.get("to_en") or "").strip()
    if a and b:
        span = ANNOTATION_SPAN.format(a=a.rstrip(" .;,"), b=b.rstrip(" .;,"))
    # 수치 — 치수선(measure)은 자체 슬롯이 있고, 경로 계열은 여기서 붙인다.
    # shape 모드는 '글자 없음'이라 값도 넣지 않는다.
    mval = (cut.get("measure_en") or "").strip()[:12]
    value = ANNOTATION_VALUE.format(m=mval) if (mval and mode != "shape") else ""
    # 화살표·X·영역 — 레퍼런스가 실제로 쓰는 도구들. 컷이 말하는 논리에 맞춰 분해기가 고른다
    if kind == "arrow":
        return ANNOTATION_ARROW.format(accent=accent, focus=focus, label=span + value + label)
    if kind == "reject":
        return ANNOTATION_REJECT.format(accent=accent, focus=focus, label=label)
    if kind == "zone":
        return ANNOTATION_ZONE.format(accent=accent, focus=focus, label=label)
    # 흐름 — 경로 전체를 굵은 띠로 이미지에 굽는다. 영상(flow_animate)은 그 위를 지나가는
    # 앞머리 하나만 움직인다. 치수선은 붙이지 않는다 (컷당 강조 하나 — 띠가 이미 강조다)
    if kind == "flow":
        return ANNOTATION_FLOW.format(accent=accent, focus=focus, label=span + value + label)
    # 빈 공간 — 채울 표면이 없어 glow 로는 표현이 안 되는 자리
    if kind == "void":
        return ANNOTATION_VOID.format(accent=accent, focus=focus, label=label)
    # 동선 — 사람·물건이 지나간 길 (물리적 흐름은 flow)
    if kind == "route":
        return ANNOTATION_ROUTE.format(accent=accent, focus=focus, label=span + value + label)
    # 뻗은 것 — 긴 대상 하나를 길이 전체에 걸쳐 점등. glow 의 선형판이라 나란히 둔다.
    # 수치를 얹지 않는 것도 glow 와 같다 (길이 자체가 메시지다).
    # 신도구 4종 — 전부 focus 하나로 성립 (trajectory 는 focus 안에 발사점·착탄점을 함께 쓴다)
    if kind == "spin":
        return ANNOTATION_SPIN.format(accent=accent, focus=focus)
    if kind == "wave":
        return ANNOTATION_WAVE.format(accent=accent, focus=focus)
    if kind == "skeleton":
        return ANNOTATION_SKELETON.format(accent=accent, focus=focus)
    if kind == "loadsplit":
        return ANNOTATION_LOADSPLIT.format(accent=accent, focus=focus)
    if kind == "trajectory":
        return ANNOTATION_TRAJECTORY.format(accent=accent, focus=focus)
    if kind == "extent":
        return ANNOTATION_EXTENT.format(accent=accent, focus=focus) + label
    # 발광 하이라이트 — 대상 전체 점등. 치수선이 없으므로 수치(measure)는 얹지 않는다.
    if kind == "glow" or mode == "glow":
        return ANNOTATION_GLOW.format(accent=accent, focus=focus) + label
    # 윤곽선 — "여러 개 중 이것" 을 가리킨다. 계측이 아니므로 치수선을 붙이지 않는다.
    if kind == "outline":
        return ANNOTATION_SHAPE.format(accent=accent, focus=focus, dim="", grid="") + label
    # 게이지 — 비율·성능. 수치가 없으면 채울 높이를 정할 수 없으므로 성립하지 않는다.
    # 곡선 그래프 — 정량 관계. 수치·라벨 없이 형태만으로 읽힌다 (measure_en 불필요).
    if kind == "graph":
        return ANNOTATION_GRAPH.format(accent=accent, focus=focus)
    if kind == "gauge":
        if not mval:
            return ""
        return ANNOTATION_GAUGE.format(accent=accent, focus=focus, m=mval)
    # 분할 비교 — 알려진 모습과 실제 모습. 양쪽이 다 있어야 성립하므로 하나라도 비면 그만둔다
    # (한쪽만 그리면 그냥 일반 컷이지 비교가 아니다).
    if kind == "versus":
        cmp_en = re.sub(r"[^\x20-\x7E]", "", (cut.get("compare_en") or "")).strip()[:110]
        if not (cmp_en and focus):
            return ""
        return ANNOTATION_VERSUS.format(
            accent=accent, compare=cmp_en.rstrip(" .;,") + ".", focus=focus,
            label=versus_labels(cut).replace("{accent}", accent))
    # 크기 비교 — 비교 대상(compare_en)이 있어야 한다. 숫자 대신 익숙한 것으로 보여준다.
    if kind == "scale":
        cmp_en = re.sub(r"[^\x20-\x7E]", "", (cut.get("compare_en") or "")).strip()[:90]
        if not cmp_en:
            return ""
        return ANNOTATION_SCALE.format(accent=accent, compare=cmp_en.rstrip(" .;,") + ".",
                                       label=label)
    # 여러 지점 동시 표시 — 하나만 가리킬 거면 zone·glow 를 쓴다
    if kind == "marker":
        return ANNOTATION_MARKER.format(accent=accent, focus=focus, label=label)
    # 빛으로 골라내기 — 대상이 작거나 배경이 복잡해 윤곽선이 안 읽히는 자리
    if kind == "spotlight":
        return ANNOTATION_SPOTLIGHT.format(accent=accent, focus=focus, label=label)
    # 개수 — 점 여러 개 + 총계. 총계가 없으면 marker 와 다를 게 없다
    if kind == "count":
        if not mval:
            return ANNOTATION_MARKER.format(accent=accent, focus=focus, label=label)
        # 'p'(명)는 화면에선 군더더기 — 점 옆 총계라는 맥락이 이미 인원을 말한다
        # (2026-08-19 사용자: "숫자만 나와도 될 것 같다"). x3 같은 곱셈 표기는 유지.
        disp = mval[:-1] if mval.lower().endswith("p") and mval[:-1].isdigit() else mval
        return ANNOTATION_COUNT.format(accent=accent, focus=focus, m=disp, label=label)
    if kind == "crack":
        return ANNOTATION_CRACK.format(accent=accent, focus=focus, label=label)
    if kind == "bracket":
        return ANNOTATION_BRACKET.format(accent=accent, focus=focus, label=label)
    # 원형 지면 그리드 — 제거했다 (2026-08-12). 조건이 shot=="wide" 하나뿐이라 실내·단면
    # 와이드에도 바닥 원판이 깔렸고, 설명이 아니라 장식으로 읽혔다. 야외 측량 컷에만
    # 어울리는 장치인데 그 조건을 shot 만으로는 가려낼 수 없다.
    grid = ""
    m = (cut.get("measure_en") or "").strip()[:12]
    # shape = UI 라벨 그대로 '글자 없음'. 수치가 있어도 새기지 않는다.
    # (예전엔 mode 를 무시하고 measure_en 유무로만 판단해 shape 인데 숫자가 나왔다)
    label = bool(m) and mode != "shape"
    # **강조 요소는 컷당 하나** — 윤곽선과 치수선이 같이 나오면 시선이 둘로 갈린다.
    # 치수선은 그 위에 수치를 얹을 때만 존재 이유가 있으므로 라벨을 새길 때만 그린다.
    # 끝점 + 수치가 둘 다 있으면 **치수선만** 그린다 — 끝점이 이미 대상을 특정하므로
    # 윤곽선은 중복이고, 강조 면적만 키운다(레퍼런스 실측 3.1% 대비 과다).
    # 끝점이 없으면 종전대로 윤곽선(+치수선) — 기존 컷은 결과가 바뀌지 않는다.
    if span and label:
        # 도면형 톤에서는 값 없는 보조 치수선 2~3개로 'CAD 도면' 밀도를 만든다 (값은 하나만)
        exclusive = (MEASURE_DRAFT_SET if norm_style(cut.get("style")) in MEASURE_DRAFT_STYLES
                     else MEASURE_ONLY_ONE)
        return ANNOTATION_MEASURE.format(accent=anno_accent(color, cut), focus=focus,
                                         m=m, span=span, exclusive=exclusive)
    dim = (", plus one slim dimension line with fine end ticks and small graduation marks"
           if label else "")
    base = ANNOTATION_SHAPE.format(accent=anno_accent(color, cut), focus=focus,
                                   dim=dim, grid=grid)
    # 치환 대상은 ANNOTATION_SHAPE 의 마지막 줄과 글자 단위로 같아야 한다 — 어긋나면
    # 금지문이 그대로 남은 채 라벨 요구가 사라진다.
    if not label:
        return base
    return base.replace(
        "Marks only — absolutely no letters, digits or words.",
        f'The dimension line carries the readout "{m}" once, in a small thin sans-serif face '
        f'matching the HUD. It is the ONLY text in the frame: never repeat it, never add '
        f'other letters or digits.')
# 레퍼런스 실측: 주석은 '설명하는 컷'에만 붙고 분위기 컷(훅·마무리·난파)은 깨끗하다.
# auto 모드는 이 규칙대로 컷마다 켜고 끈다 — 전부 붙이면 정보 과잉이 된다.
ANNO_AUTO_STYLES = {"tech3d", "blueprint", "xsection", "sci3d", "docu3d",
                    "aerial", "arch3d"}   # 전경 2종은 발광 하이라이트가 걸리는 톤
ANNO_AUTO_BEATS = {"constraint", "pivot", "solution"}
ANNO_SKIP_BEATS = {"hook", "closing"}


def _video_anno_kind(img_anno, cut, has_image):
    """영상 주석의 기본 동작. 시작 이미지에 이미 HUD가 그려져 있으면 'animate'(그걸 살린다),
    깨끗한 이미지거나 이미지가 없으면 'draw'(영상에서 새로 켠다).
    이미지에 굽고 영상에서 또 그리면 HUD가 겹쳐서 두 벌로 나온다.
    컷별 이미지 주석 설정(cut['anno'])이 있으면 그게 우선 — 전역만 보면
    '이 컷만 주석 없음'으로 뽑은 깨끗한 이미지에 animate 를 걸게 된다."""
    if not has_image:
        return "draw"
    mode = anno_for_cut(cut.get("anno") or img_anno, cut, "full")
    return "animate" if annotation_block(mode, cut) else "draw"


def anno_for_cut(mode, cut, auto_val="shape"):
    """이 컷에 주석을 붙일지 판단. auto면 '설명 컷'에만 auto_val 을 돌려준다.
    이미지(shape/full)와 영상(draw/animate) 양쪽이 같은 규칙을 쓴다.
    이미지 auto 는 컷 성격에 따라 HUD(shape/full) 또는 발광 하이라이트(glow)로 풀린다."""
    if not mode:
        return ""
    if mode != "auto":
        return mode
    glow = anno_kind_for_cut(cut) == "glow"
    if glow and auto_val in ("shape", "full"):
        auto_val = "glow"
    beat = cut.get("beat") or ""
    if beat in ANNO_SKIP_BEATS:
        # 훅은 수치가 있으면 예외 — "20km" 한 줄이 첫 2초에 시청자를 잡는다.
        # 발광 하이라이트도 예외 — 훅 전경에서 구조물이 통째로 점등되는 게 레퍼런스 룩.
        # (HUD 는 계속 훅에 안 붙는다.) 마무리는 여운이 목적이라 무엇이든 끈다.
        if beat == "hook" and (cut.get("measure_en") or "").strip():
            return auto_val
        if beat == "hook" and glow and (cut.get("focus_en") or "").strip():
            return auto_val
        return ""
    if norm_style(cut.get("style")) in ANNO_AUTO_STYLES:
        return auto_val
    if (cut.get("beat") or "") in ANNO_AUTO_BEATS:
        return auto_val
    return ""
def bp_is_image(model_id):
    """이미지 모델인가(장 단위) vs 영상 모델인가(토큰 단위). 단위가 다르면 한 통에
    합칠 수 없다 — 이미지 몇 장에 영상 계정이 소진 판정되는 사고를 막는다."""
    return "seedream" in (model_id or "").lower()


def bp_model_label(model_id):
    """콘솔 모델 ID → 화면용 짧은 한글 이름. 못 알아보면 벤더 접두어만 떼고 그대로 쓴다."""
    s = (model_id or "").lower()
    if "seedance" in s:
        base = "씨댄스"
    elif "seedream" in s:
        base = "씨드림"
    else:
        return re.sub(r"^(bytedance|dola|volc)[-_]", "", model_id or "?", flags=re.I)
    m = re.search(r"(\d+)[-.](\d+)", s)
    ver = f" {m.group(1)}.{m.group(2)}" if m else ""
    tier = " Pro" if "pro" in s else (" Lite" if "lite" in s else "")
    return base + ver + tier


def reg_suggest_from_cuts(cuts):
    """컷분해 결과에서 등록부 후보를 뽑는다 — ① 캐논 반복: 같은 subject_en 앞머리가
    3컷 이상 반복되면 고정 피사체다 (지침이 캐논을 "토씨 하나 바꾸지 말고 복사"라고
    강제하므로 접두 일치로 잡힌다) ② product 컷. 라벨·묘사·해당 컷 목록을 돌려줘서
    사용자가 클릭 한 번으로 등록 + 컷 자동 체크까지 가게 한다."""
    groups = {}
    for c in cuts:
        raw = re.sub(r"\s+", " ", (c.get("subject_en") or "").strip())
        if len(raw) < 30:
            continue
        k = raw.lower()[:60]
        g = groups.setdefault(k, {"desc": raw[:200], "cuts": []})
        g["cuts"].append(int(_num(c.get("no"), 0)))
    out = []
    for g in groups.values():
        if len(g["cuts"]) >= 3:
            out.append({"desc": g["desc"], "cuts": sorted(g["cuts"]), "kind": "obj"})
    covered = {no for g in out for no in g["cuts"]}
    for c in cuts:
        if (c.get("type") or "") == "product" and (c.get("subject_en") or "").strip():
            no = int(_num(c.get("no"), 0))
            if no not in covered:
                out.append({"desc": re.sub(r"\s+", " ", c["subject_en"].strip())[:200],
                            "cuts": [no], "kind": "obj"})
    return out[:4]


def cap_anno_cuts(cuts, anno_max=4):
    """한 영상에서 강조를 켤 컷 수를 상한까지 줄인다. 끈 컷 수를 돌려준다.

    강조가 매 컷 켜지면 '가끔 켜져 눈길을 끄는 장치'가 아니라 배경이 된다 — 시청자 시선이
    대사가 아니라 화면 여기저기의 HUD 를 따라다닌다. auto 게이팅이 **실제로 켜줄** 컷만
    세고, 상한을 넘으면 약한 것부터 끈다.

    끄는 방법은 **컷별 주석 설정을 'none' 으로 두는 것**이다 — focus_en 을 지우면 분해기가
    골라준 영문 문구가 사라져 사용자가 되살리려면 직접 영작해야 하고, 화면에는 왜 비었는지
    단서도 남지 않는다. 'none' 이면 컷 카드의 주석 셀렉트가 '이 컷은 없음'으로 보이고,
    '자동'으로 되돌리면 문구가 그대로 살아난다 (measure_en 도 남는다 — 편집 지시로 쓰인다).
    남기는 우선순위 — ① 수치가 있는 컷 ② 설명 비트(constraint·pivot·solution) ③ 나머지.
    anno_max <= 0 이면 무제한(예전 동작). 이미 꺼둔 컷은 다시 세지 않는다(여러 번 불러도 같음)."""
    if anno_max <= 0:
        return 0
    on = [c for c in cuts if (c.get("focus_en") or "").strip()
          and (c.get("anno") or "") != "none"
          and anno_for_cut("auto", c, "shape")]
    if len(on) <= anno_max:
        return 0

    def _rank(c):
        return (0 if (c.get("measure_en") or "").strip() else
                1 if (c.get("beat") or "") in ANNO_AUTO_BEATS else 2,
                c.get("no") or 0)
    off = sorted(on, key=_rank)[anno_max:]
    for c in off:
        c["anno"] = "none"
    return len(off)


NEGATIVE_SNAP = """Avoid: professional photography, studio lighting, cinematic color grading,
shallow depth of field, bokeh, HDR, dramatic composition.
Avoid: stock-photo smiles, models, glamour posing, flawless retouched skin."""
NEGATIVE_CLEAN = """Avoid: cluttered background, harsh direct flash, motion blur,
compression artifacts, distracting props."""
NEGATIVE_FLAT = """Avoid: photographic texture, realistic skin, lens effects,
3D shading, gradients, drop shadows."""
# 만화 요약 톤 — 실패 모드가 illust 와 다르다. '정교한 애니 작화'(큰 반짝이는 눈·머리
# 하이라이트·셀 그림자)로 흐르는 것이 가장 흔하고, 그러면 단순 만화 느낌이 사라진다.
NEGATIVE_ANIME = """Avoid: photographic texture, 3D render, cel shadows, gradients, gloss,
glowing highlights, painterly rendering.
Avoid: detailed modern anime art — large glossy reflective eyes, hair highlight strands,
thin tapering linework, realistic body proportions, complex costume detail.
Avoid: busy or detailed backgrounds."""
# 플랫 톤(illust·blueprint)에 강조가 붙으면 "gradients·발광 금지"와 HUD 의 "luminous /
# soft neon bloom" 요구가 한 프롬프트 안에서 정면충돌한다 — 모델이 둘 중 하나를 버리므로
# 강조가 뭉개지거나 그림이 입체가 된다. 강조 오버레이만 예외로 열고 그림은 계속 플랫하게.
NEGATIVE_FLAT_ANNO = """Avoid: photographic texture, realistic skin, lens effects,
3D shading, gradients and drop shadows **in the artwork itself**.
The annotation overlay described above is the one exception — its thin strokes may glow
and bloom; the illustration underneath stays completely flat."""
# 밝기 — 톤과 직교하는 축. 같은 자료 화면도 정보·교양이냐 사건·미스터리냐에 따라
# 분위기가 갈리는데, 톤을 두 벌씩 만들면 관리가 두 배가 된다. 한 줄로 얹는다.
# 톤 자체를 뒤엎지 않고 **빛과 바탕만** 건드리는 게 요령이다 — 재질 지시와 싸우면
# 종이가 종이가 아니게 된다.
MOOD_LINES = {
    "dark": ("Overall the frame runs dark and low-key: the ground behind and beneath the subject "
             "is deep and shadowed, light comes from one side and falls off fast, and everything "
             "outside the lit area sinks toward black. Materials keep their own character but "
             "read a stop or two darker, and the single accent colour is the brightest thing in "
             "the frame. Weighted, serious, night-side."),
    "light": ("Overall the frame runs bright and open: the ground is pale and evenly lit, shadows "
              "are soft and short, and nothing sinks into darkness. Clean, calm, daylight-side."),
}

NEGATIVE_PAPER = ("Avoid: digital illustration, cartoon, 3D render, glossy surfaces, gradients,\n"
                  "smooth vector shapes, clutter, and any element that does not look physically\n"
                  "cut from real paper and laid on the table.")

NEG_BY_STYLE = {"snap": NEGATIVE_SNAP, "archive": NEGATIVE_SNAP,
                # 자료 이미지 — 종이로 안 보이면 실패다. 3D·광택·그라데이션을 통째로 막는다.
                "collage": NEGATIVE_PAPER, "mapboard": NEGATIVE_PAPER,
                "vector": NEGATIVE_FLAT,   # 평면 벡터 — 사진 질감·3D 음영 금지
                "productshot": NEGATIVE_CLEAN,   # 스튜디오 사진 — 실사 질감이 정체성이라 CLEAN
                "chalkboard": NEGATIVE_FLAT,     # 분필 도해 — 사진 질감 금지
                "xray": NEGATIVE_CLEAN,          # 방사선 사진 — 밀도 표현이라 실사 계열
                "illust": NEGATIVE_FLAT,
                # labmacro는 스튜디오 조명이 정체성이라 SNAP(스튜디오 금지)이 아닌 CLEAN
                "labmacro": NEGATIVE_CLEAN,
                "blueprint": NEGATIVE_FLAT,   # 도해 — 사진 질감 금지
                "planline": NEGATIVE_FLAT,    # 평면 도면 — 사진 질감·원근 금지
                # 클레이는 '3D 형상'이라 사진 질감 금지(FLAT)를 걸면 입체감까지 죽는다 → CLEAN
                "claysection": NEGATIVE_CLEAN,
                "blackstage": NEGATIVE_CLEAN,    # 검은 무대 — 조각 질감이 정체성이라 CLEAN
                "greycast": NEGATIVE_CLEAN,      # 회색 마네킹 — 3D 렌더 질감이 정체성
                "whitecast": NEGATIVE_CLEAN,     # 흰 모형 세계 — 마찬가지
                "tabletop": NEGATIVE_CLEAN,      # 미니어처 모형 — 실사 재질감이 정체성
                "story3d": NEGATIVE_CLEAN,       # 3D 시네마틱 — 실사 질감을 원한다
                "toy3d": NEGATIVE_CLEAN,         # 피규어 3D — 마찬가지
                # 만화 요약 — 플랫 셀이 정체성. 3D·음영·정교한 애니 작화로 흐르면 톤이 깨진다
                "anime": NEGATIVE_ANIME,
                "aerial": NEGATIVE_CLEAN, "xsection": NEGATIVE_CLEAN,
                "docu3d": NEGATIVE_CLEAN,
                # 3D 3종은 실사 질감을 원하므로 NEGATIVE_FLAT(사진 질감 금지)을 쓰면 안 된다 → CLEAN
                "sci3d": NEGATIVE_CLEAN, "tech3d": NEGATIVE_CLEAN, "arch3d": NEGATIVE_CLEAN,
                # game 은 생활감 밀도가 정체성이라 CLEAN(어수선함 금지)을 쓰면 안 된다
                "cine": "", "game": ""}

SHOT_LINES = {
    "macro": "extreme macro close-up, structure filling the frame",
    "cutaway": "clean cross-section cutaway showing the internal structure, sliced open",
    "wide": "wide shot showing the whole space and context",
    "close": "close crop on the subject, taken a bit too close",
    "pov": "first-person view, own hand visible at the bottom of frame",
    "object": "the object alone on a plain surface, nothing else in frame",
    "screen": "a phone or monitor screen photographed by another phone, glare and moiré visible",
}
# ── 리빌 방식 (2026-08-12 신설) ─────────────────────────────────────
# 왜 별도 축인가: 지금까지 '자르는 방식'이 shot 안에 cutaway 하나로 들어가 있었다.
# 그런데 shot 은 화각(macro·wide·close)과 배치(object·screen)를 담는 필드라, 리빌이 섞이면
# "와이드로 잡은 부분절개" 같은 조합을 표현할 수 없다. 톤(style)에 넣는 것도 답이 아니다 —
# 그러면 '클레이 + 부분절개', '실사 + 부분절개'마다 톤을 새로 만들어야 해서 조합이 폭발한다.
# 축을 분리하면 리빌 6종 × 톤 14종이 전부 조합 가능해진다.
#
# ⚠ CAD 소프트웨어 기능명(clipping plane·section box·live section·3D section 등)은 일부러
#   넣지 않았다. 이미지 모델에게는 전부 '잘라서 속을 보여줘'라는 같은 말이라, 유사어를 여러 개
#   주면 지시끼리 싸운다. 결과가 실제로 달라지는 방식만 남긴 폐쇄 목록이다.
REVEAL_LINES = {
    "full_section": "Reveal: cut clean through the whole subject with one flat sectional plane, "
                    "the exposed cut faces showing the real material thickness inside.",
    # 외형이 곧 상징인 대상(피라미드·목마·성벽)에 쓴다. 통째로 자르면 '이게 뭐였지'를 잃는다.
    "partial_cutaway": "Reveal: a partial cutaway — only a limited part of the outer shell is "
                       "removed, exactly over the area being explained, so the interior is open "
                       "there while the rest of the object stays whole. The overall outline stays "
                       "instantly recognisable, and the cut edge is clean with visible material "
                       "thickness, not torn or melted.",
    "breakout": "Reveal: a small local breakout — one bounded patch of the surface is removed like "
                "a window, just deep enough to expose what sits directly behind it. Everything "
                "outside that patch is untouched, and the broken-out edge is clean and sharp.",
    # 껍질을 투명하게 만드는 X-ray 와 다르다: 실물은 끝까지 불투명하고, 내부만 겹쳐 보인다.
    "ghosted": "Reveal: a ghosted view — the outer form stays in place but is rendered faint and "
               "semi-transparent, while the internal structure behind it reads sharp and solid "
               "through it. The outer silhouette and its main contours remain clearly visible so "
               "the interior is always understood as being inside that shape.",
    "layer_reveal": "Reveal: the outermost layer is lifted away as one piece to expose the layer "
                    "directly beneath it, both layers clearly separate and complete. Only that "
                    "one layer is removed — everything deeper stays covered.",
    # 단 분리 — 층·단·겹으로 '쌓인' 것 전부에 쓴다(건물 층·배 갑판·지층·필터 단·서버 랙).
    # 분해뷰([5-2])와 갈리는 지점은 **축이 하나**라는 것이다: 수직으로만 벌려 원래 실루엣이
    # 그대로 읽힌다. 분해뷰는 여러 방향으로 벌어져 형태가 흩어진다.
    "stack_split": "Reveal: the subject is separated into the layers it is stacked from — floors, "
                   "decks, strata, plates — lifted apart along one single vertical axis with even "
                   "gaps between them. Every layer stays flat, level, complete and in its original "
                   "order, directly above the one below, so the whole silhouette still reads as one "
                   "object. Nothing rotates, tilts or scatters sideways.",
    # 투시 — 유일하게 **자르지 않는** 리빌이다. 껍질을 밀도로 통과해 본다.
    # ghosted 와 갈리는 지점: ghosted 는 외형이 반투명해지고 내부가 '실물'로 보이지만,
    # 이건 전체가 방사선 사진처럼 밀도 계조로만 읽힌다.
    "xray": "Reveal: an x-ray view — the outer surface is not cut or removed at all, but rendered "
            "as if seen through by radiation, so everything inside shows purely as density: dense "
            "parts bright and solid, thin material faint and translucent, hollow spaces dark. "
            "There is no cut edge and no piece taken away; the outer contour stays faintly visible "
            "around the interior.",
}
REVEAL_LABELS = {"": "없음 (안 자름)",
                 "full_section": "전체 단면 — 통째로 관통",
                 "partial_cutaway": "부분 절개 — 외형 유지 + 일부만 개방",
                 "breakout": "국부 파냄 — 한 구역만 창처럼",
                 "ghosted": "고스트 — 외형 반투명 + 내부 선명",
                 "layer_reveal": "겉껍질 들어냄 — 한 겹만",
                 "stack_split": "단 분리 — 층·단을 수직으로 띄움",
                 "xray": "투시 — 안 자르고 밀도로 비침"}


def cut_reveal(cut):
    """이 컷의 리빌 방식. 예전 드래프트는 shot='cutaway' 로 '통째로 자름'을 표현했으므로
    reveal 이 비어 있으면 그걸 전체 단면으로 읽는다 (기존 컷 데이터가 조용히 깨지지 않게)."""
    r = (cut.get("reveal") or "").strip().lower()
    if r in REVEAL_LINES:
        return r
    return "full_section" if cut.get("shot") == "cutaway" else ""


def is_cut_open(cut):
    """속을 연 컷인가 — 영상에서 '다시 열지 마라'(기하 잠금)를 걸 대상 판별."""
    return bool(cut_reveal(cut)) or norm_style(cut.get("style")) == "xsection"


# ── 근거 수준 표기 (문화유산 컷) ────────────────────────────────────
# 런던 헌장의 원칙 — 확인된 것과 추정한 것을 시각적으로 구분한다. 우리에겐 두 가지 값어치가
# 있다: ① 역사 콘텐츠의 신뢰도 ② GPT 마스터 프롬프트 §23('모르는 구조를 지어내지 마라')의 답.
# 모른다고 안 보여주면 화면이 비고, 아는 척 그리면 거짓이 된다 → 확실성을 그림으로 말한다.
EVIDENCE_LINES = {
    "solid": "Everything shown is surviving fabric: render it fully opaque and photoreal, with "
             "real wear, weathering and damage left visible.",
    "inferred": "The reconstructed parts are an informed inference, and they look it: they carry "
                "the same materials as the surviving fabric but read slightly cleaner and "
                "quieter, clearly a considered restoration rather than a photograph of what "
                "survives. Anything that actually survives stays fully opaque and photoreal.",
    "hypothetical": "The reconstructed parts are only a hypothesis and must read that way: show "
                    "them as restrained luminous wireframe geometry — thin edges and faint "
                    "transparent surfaces, no solid material, no texture. Whatever actually "
                    "survives stays fully opaque and photoreal beside it, so the eye can tell "
                    "instantly which is evidence and which is a guess.",
}
EVIDENCE_LABELS = {"": "없음",
                   "solid": "현존 — 남아 있는 것만",
                   "inferred": "추정 — 근거 있는 복원",
                   "hypothetical": "가설 — 와이어프레임으로"}

STYLE_REF_LINE = ("Match the visual style, lighting, color grade and level of realism of the "
                  "reference image(s). Do not copy their subject or composition.")
# 피사체 시트 — 캐릭터 시트(anime 전용)의 사물판. 여러 컷에 같은 구조물·기계·유물을
# 유지하는 수단이다. 캐논 문구(글로 적은 묘사)는 컷마다 해석이 달라지지만, 이건 그림이라
# 편차가 훨씬 작다. STYLE_REF_LINE 과 지시가 정반대라 한 프롬프트에 같이 넣을 수 없다.
SUBJECT_SHEET_LINE = ("The first reference image shows the exact subject of this shot. Reproduce "
                      "that same object: the same shape, proportions, materials, colour and wear, "
                      "down to its distinctive details. Only the camera angle, framing, lighting "
                      "and surroundings follow the SUBJECT description above — the object itself "
                      "must be recognisably the very same one, not a similar one.")
# 캐릭터 시트는 STYLE_REF_LINE 과 지시가 정반대다 — 저쪽은 '피사체를 복사하지 마라',
# 이쪽은 '이 인물을 그대로 가져와라'. 한 프롬프트에 둘 다 넣으면 반드시 하나가 깨지므로
# anime 톤 + 시트가 있을 때만 이 문장으로 갈아끼운다 (_build_prompt).
CHAR_SHEET_LINE = ("The first reference image is a character sheet. Use its characters exactly as "
                   "drawn — the same faces, hair, body proportions, outfits and colors — and keep "
                   "its drawing style. Do NOT copy the sheet itself: ignore its white background, "
                   "its side-by-side lineup and any labels on it, and place the characters into "
                   "the scene described above instead.")
CHAR_PICK_LINE = ("Only {who} from the sheet appear in this shot; the other characters are not "
                  "in frame.")
# 📇 등록부 — 대상별 "개별 그림"만 컷에 붙인다. 시트 통째 참조는 모델이 엉뚱한 대상을
# 골라오는 실사고가 있어(이식 가이드 2026-08-13) 구조로 피한다. 라벨 글자 대신 묘사로 지목.
REG_SHEET_LINE = ("The first {n} reference image(s) each show ONE exact subject for this "
                  "shot: {descs}. Copy each of them exactly — the same face, shape, "
                  "proportions, colours, materials, outfit and distinctive details — and "
                  "keep them clearly recognisable as the very same ones. Do NOT copy the "
                  "reference backgrounds or layout: ignore the plain backdrop and any "
                  "lineup, and place the subjects naturally into the scene described above.")
REG_COUNT_LINE = ("The scene contains each referenced subject exactly once. No duplicates "
                  "of them anywhere, and no other person or object in the scene may "
                  "resemble them — give any extras clearly different looks.")
# 시트 생성 프롬프트 — 작품당 1회. 정면 전신 한 장이면 되고 턴어라운드는 오히려 해롭다
# (여러 각도가 한 장에 있으면 모델이 뭘 쓸지 못 정해 컷마다 각도가 섞인다).
# 효과가 큰 건 ① A~D 라벨 ② 흰 배경·전신 정면 ③ 인물끼리 머리색·실루엣이 확실히 갈리는 것.
CHAR_SHEET_PROMPT = """A character reference sheet with original characters standing side by side
in a row, each labelled with a single letter A, B, C, D above them.

{chars}

Include a few small cartoon emotion symbols beside the characters as extra icons:
sweat drops, tear streams, spark marks, surprise burst lines.

Style: simple Japanese cartoon style, hand-drawn look, roughly 2.5-head-tall proportions,
round faces, small black dot eyes, simple mouths, thick uniform dark outlines, bright flat
colors, completely flat cel style with NO shading, NO gradients, NO gloss.
Full body, front view, plain clean white background, characters clearly separated.

These are original characters: they must not resemble any real person, and must not reproduce
the character designs, costumes, team uniforms, emblems or logos of any existing manga, anime,
game or film. No lettering, numbers or brand marks on clothing or props (the A/B/C/D labels
above the characters are the only text).

Avoid: 3D render, glossy shading, gradients, detailed modern anime eyes, realistic proportions,
complex costume detail, busy background."""


def sheet_chars(cut):
    """이 컷에 등장하는 캐릭터 라벨 — ['A','B']. 분해기는 리스트로, 사람이 손으로 고칠 땐
    'A,B' 문자열로 들어올 수 있어 양쪽을 받는다. 시트 라벨은 A~Z 한 글자로 제한한다
    (모델이 지목할 수 있는 형태여야 한다 — 이름을 쓰면 시트의 어느 인물인지 못 짚는다)."""
    v = cut.get("chars")
    if isinstance(v, str):
        v = re.split(r"[,\s/·]+", v)
    out = []
    for x in (v or []):
        s = str(x).strip().upper()[:1]
        # ⚠ str.isalpha() 는 한글에도 True 다 — 그대로 두면 "강백호"가 'ㄱ' 라벨이 되어
        #   "character 강" 이라는 지목이 프롬프트로 나간다. 시트 라벨은 ASCII A~Z 뿐이다.
        if "A" <= s <= "Z" and s not in out:
            out.append(s)
    return out[:4]

SCENE_SPLIT_PROMPT = """당신은 유튜브 쇼츠 채널의 이미지 디렉터다.
아래 나레이션 대본을 화면에 깔 정지 이미지 컷으로 분해하라.

[0. 대본 형식 자동 인식 — 먼저 판별하고 그에 맞게 분해하라]
A) 건축사전형(습니다체 설명형): 모순 훅 → 제약(뻔한 답 기각) → "환장할 노릇" → "발상을 뒤집습니다" → 해법 → 생활 비유 → "이렇게 탄생한 겁니다"
B) 썰쇼츠형(음슴체 이야기형): 결과 선공개 훅 → 결핍/위기 → "근데 진짜 충격적인 건" → 반전 보상 → 감정 낙인("인정"/"극락")
C) 작품요약형(만화·애니·영화 한 편 요약): 결말까지 압축한 줄거리. 결과 선공개 훅 → 입문·계기 →
   관계·라이벌 → 목표 제시 → 위기 → 절정 → 결말 여운.
   **표 형태로 들어올 수 있다** — `장면 | 나레이션 | 화면 내용` 처럼 행마다 컷이 이미 나뉘어 있으면
   **그 나눔을 그대로 존중하라**(합치거나 쪼개지 마라). '나레이션' 칸이 line, '화면 내용' 칸이
   subject_en 의 재료다. 표가 아니라 줄글이면 평소대로 네가 나눠라.
   이 형식은 style 을 전부 anime 로 고정하고, [4-c] 의 chars 를 반드시 채운다.

[1. 분해 규칙]
1. 컷은 {n_cuts}개 내외.
   **한 컷의 대사는 공백 포함 {chars_lo}~{chars_hi}자**로 묶어라 — 낭독 4~8초에 해당한다.
   짧은 문장은 **바로 앞뒤 문장과 한 컷으로 묶는다.** 단 장면·피사체가 바뀌는 자리는 묶지 마라.
   (2초짜리 컷은 영상 모델이 만들 수 없어 결국 앞뒤와 합쳐진다 — 처음부터 묶는 편이 낫다)
   **지시어 정합 — 묶는 방향을 정하는 규칙**: "이게/이 문/그것"처럼 앞 문장의 피사체를
   가리키는 대사는 반드시 **그 피사체가 화면에 보이는 컷에** 묶는다.
   (예: "대체 이게 어떻게 성을 무너뜨렸을까요?"는 목마 컷의 **마지막** 문장이지, 다음 장면
   (야영지)의 첫 문장이 아니다 — 화면에 없는 것을 '이게'라고 부르면 시청자가 길을 잃는다)
   **대사 전량 커버**: 대본의 모든 문장은 순서대로 **정확히 한 컷의 line 에** 속해야 한다 —
   누락·중복·바꿔쓰기 금지, line 은 원문을 글자 그대로 복사한다. (자막·음성 타이밍이 line 의
   글자 수로 정렬되므로, 한 문장이 빠지거나 달라지면 뒤 컷 전체의 타이밍이 밀린다)
2. **첫 문장(훅)은 반드시 독립 컷.** 가장 자극적이고 이상한 그림을 뽑아라.
3. **`chain`(이어짐) — 앞 컷과 같은 공간·같은 대상을 연속으로 보여줄 때만 true.**
   판단 기준 한 줄: "**앞 컷의 그림에서 카메라가 멈추지 않고 그대로 이어서 움직여도 말이 되는가?**"
   (영상 생성은 앞 컷 이미지에서 출발해 이 컷 이미지로 도착한다 — 두 그림이 한 공간 안에
    있어야 그 사이를 이어 그릴 수 있다. 공간이 다르면 모델이 억지로 워프시켜 어색해진다.)
   · 켠다: ①한 공간을 파고들 때 (전경 → 다가감 → 내부) ②같은 대상의 상태가 변할 때
     (물이 차오름, 구조물이 무너짐, 불이 번짐)
   · 끈다: 장소·피사체·시대가 바뀌면 **무조건 false**. 도해·자료화면으로 넘어갈 때도 false.
   · 묶음의 **첫 컷은 false**, 이어지는 2~3번째만 true.
   · **한 영상에 묶음은 최대 2개, 묶음당 최대 3컷.** 대부분의 컷은 false 다 —
     장면이 바뀌는 게 정상이고, 이어짐은 예외적으로 쓰는 장치다. 애매하면 false.
3-1. **전환의 대비 — 몰입은 '이어짐'만큼 '끊김'이 만든다.**
   · `chain=false` 인 컷은 **장면 전환 지점**이다. 앞 컷과 **확실히 다른 그림**을 잡아라 —
     같은 각도·같은 거리에서 피사체만 바꾸면 전환이 아니라 실수처럼 보인다.
     (거리를 바꾸거나 — 원경↔매크로, 시점을 바꾸거나 — 밖↔안, 밝기를 바꿔라)
   · 이어짐 묶음은 **한 방향으로 진행**시켜라. 전경 → 다가감 → 내부처럼 한 걸음씩 들어가야지,
     들어갔다 나왔다 하면 어지럽다.
   · 대본의 전환어("그래서", "그런데 여기서", "진짜 문제는")가 나오는 자리는 **반드시 chain=false**.
     말이 꺾이는 지점에서 화면도 같이 꺾여야 시청자가 따라온다.
   · **같은 핵심 피사체의 '전신 샷'을 체인이 아닌데도 연달아 놓지 마라.** 컷은 독립 생성이라
     같은 물건도 매번 디테일이 조금씩 다르게 나온다 — 전신이 연속되면 그 차이가 바로 보인다.
     캐논 문구([1]의 반복 피사체 규칙)로 편차를 줄이되, **배치로도 숨겨라**: 대사가 허락하면
     사이에 다른 피사체 컷을 끼우거나, 한쪽을 부분 디테일(밧줄 매듭·바퀴·나뭇결 매크로)로
     잡아라. 부분 클로즈업은 '같은 물건의 일부'로 읽혀 디자인이 달라도 티가 나지 않는다.
4. 숫자·등급은 글자로 그리지 마라. 그 숫자가 뜻하는 상태를 사물로 보여준다.
5. 특정 실제 제품을 지목하는 컷은 type=product, `search_ko` 에 검색어. subject_en 도 채운다 —
   기본은 실물 검색이지만 사용자가 [AI로 전환]할 수 있어야 한다 (상표·로고는 빼고 일반형으로 묘사).
6. 브랜드명·로고·모델명 금지. 사람은 손·팔·뒷모습·실루엣 위주, 얼굴은 알아볼 수 없게.
   (game 톤 컷만 예외 — 스타일라이즈드 게임 캐릭터 얼굴은 보여도 된다. 실존 인물 닮기는 계속 금지)
7. **반복 피사체 캐논 — 2컷 이상 다시 나오는 핵심 피사체(주인공 구조물·기계·물건·건물)는
   생김새를 한 번 확정하고, 등장하는 모든 컷에 같은 문구로 써라.**
   · 재질·색·형태·비율·마모 상태까지 박은 상세 영어 묘사 한 구(캐논 문구)를 만들고, 그 피사체가
     나오는 **모든 컷의 subject_en 앞머리에 토씨 하나 바꾸지 말고 그대로 복사**하라.
     컷마다 달라지는 것(구도·거리·행위·주변 상황·홀로그램)은 캐논 문구 **뒤에** 덧붙인다.
     (예: 캐논 "a colossal wooden horse built from weathered dark ship planks, rope lashings
      and bronze nails, standing on a crude wheeled sled" → 컷A "..., towering before the
      city gate at dawn" / 컷B "..., split open lengthwise revealing the hollow interior")
   · 각 컷은 서로를 모르는 독립 생성이라 **같은 문구가 유일한 연결고리다.** 컷마다 묘사를
     새로 쓰면 매번 다른 물건이 나온다 — weather_en 의 '같은 현장 = 같은 대기' 규칙과 같은 이유.
   · 배경 소품·행인처럼 매번 달라도 티 안 나는 것은 제외. 이야기의 주인공 피사체에만 써라.
   · **인물도 캐논 대상이다.** 2컷 이상 나오는 주요 인물(장군·기술자·목격자)은 나이·체격·
     머리·수염·의상·소지품까지 박은 영어 묘사 한 구를 확정해 같은 방식으로 복사하라.
     **얼굴 생김새는 적지 마라** — 매번 창작 얼굴이어야 하고(실존 인물 닮기 금지),
     알아보게 하는 것은 실루엣·의상·소지품이다.
     (캐릭터 시트는 anime 톤에서만 붙는다 — game 톤 인물은 이 문구가 유일한 연결고리다)
   · **캐논에는 이야기 내내 변하지 않는 것만 담아라.** 공정·시간이 진행되는 대상이면
     불변 부분만 캐논에 넣고, 단계에 따라 생기고 사라지는 것은 컷별로 써라.
     자문 한 줄: **"이 문구를 첫 컷과 마지막 컷에 똑같이 붙여도 둘 다 말이 되는가?"**
     (예: 공사 현장 캐논에 '바닥에서 솟은 H기둥'을 넣으면, 그 기둥을 아직 안 박은
      앞 컷들에도 기둥이 서 있게 된다 — 기둥은 캐논이 아니라 컷별 묘사다)
   · **캐논이 그 컷의 화각과 어긋나면 줄여 써라.** 클로즈업·매크로 컷 앞머리에 전경 묘사를
     붙이면 이미지 모델이 앞머리를 주 피사체로 읽어 **클로즈업이 와이드로 나온다.**
     그런 컷에는 캐논에서 재질·색·마모만 남기고 전체 형태·주변 환경은 빼라.
   · **자세·상태가 캐논과 다른 컷**(엎어짐·쓰러짐·분해됨)은 캐논 **앞에** 상태를 먼저 선언하라
     (예: "toppled on its side across the road: a colossal …"). 캐논 뒤에 붙이면 묻힌다.

8. **subject_en 에 톤·매체 어휘를 쓰지 마라.**
   subject_en 은 '무엇이 찍혔는가'만 적는 자리다. 어떤 질감·색·매체로 보일지는 style 필드가
   정하고 앱이 그 문구를 갖고 있다. subject_en 에 톤 어휘를 쓰면 사용자가 화면에서 톤을
   일괄 지정해도 **그 컷만 원래 톤으로 남아** 한 영상 안에서 화면이 섞인다.
   · 쓰지 마라 — cinematic / film grain / grainy / faded / vintage photograph /
     black-and-white / documentary footage / archival photo / shallow depth of field /
     bokeh / anamorphic / lens flare / studio lighting / drone shot / 3D render /
     flat vector / matte clay model / monochrome / blueprint drawing
   · 써도 된다 — 사물·재질·색·마모·자세·배치, 그리고 시점과 거리
     ("seen from high above", "framed close on its face"), 현장에 실제로 있는 것(먼지·물·불).
     '드론으로 찍은'은 매체다 → "seen from high above" 로 써라.
   · 예외 셋 — 톤이 아니라 연출 장치이고 **앱이 이 문구로 컷을 알아본다.** 그대로 써라:
     ① 홀로그램([3-1])의 "… while the real scene around it stays still and photoreal"
     ② 분해뷰([5-2])의 "shown in a compact exploded view"
     ③ 그래픽([4])의 "already drawn as a flat cyan graphic overlay,"
   · 흑백 자료화면·항공·클레이 모형이 필요하면 **어휘가 아니라 style 로 말하라**
     (archive / aerial / claysection). 그래야 사용자가 톤을 바꿀 때 같이 따라간다.

[2. beat — 이 컷이 대본에서 맡은 역할. 반드시 하나 부여]
hook(훅) / context(정체·결핍·배경) / constraint(제약·뻔한답 기각·에스컬레이션) /
despair(절망 비트) / pivot(발상 전환 선언) / solution(해법·반전 보상) /
analogy(생활 비유·대조군) / closing(여운·감정 낙인)

[3. beat별 톤 기본값 — style 을 이 기준으로 채워라]
docu3d 가 이 채널의 대표 톤이다. 건축물·유적·구조물·현장을 '그 자리에 서서' 보여주는 컷,
즉 훅·구조 설명·해법 증명 컷의 기본값으로 docu3d 를 먼저 검토하라.
hook→docu3d 또는 cine / context(과거·역사·서사)→archive, (현재 상황)→snap
constraint·despair→docu3d 또는 tech3d(단면으로 문제가 '생기는' 과정)
pivot·solution→docu3d(현장 재현) 또는 tech3d(도해로 원리를 짚을 때)
analogy→snap(부엌·욕실 등 생활 장면) / closing→docu3d·arch3d(전경) 또는 snap
미시·인체는 sci3d, 전경·건설·지형은 arch3d. 실사로 못 만드는 과장은 illust.
실물 실험·시연·제품 데모(테이블 위에서 만지고 반응이 일어나는 장면)는 labmacro.
**단, 대본이 한 현장(건축물·유적·공사장·자연 지형)의 이야기를 이어가는 중이라면
labmacro·xsection·tech3d 로 빠지지 마라.** 이 톤들은 배경을 비우고 스튜디오·검은 배경으로
가기 때문에, 현장 이야기 한복판에 끼면 시청자가 장소를 잃는다. 그 자리에서 원리를 설명해야
하면 docu3d 를 유지하고 subject_en 에 클로즈업 대상을 적어라
(예: "close on two granite blocks locking together on the wet rock, storm sea behind").
실험실·공장·테이블이 실제로 대본에 나올 때만 위 세 톤을 써라.
설계·치수·구조 비교·금지(X) 설명은 blueprint(청사진 도해).
**치수·두께·구조 자체가 요점인 컷**은 claysection(클레이 단면) — 색과 질감을 통째로 죽인
무채색 모형이라 형상과 치수만 남는다. 재질 이야기(화강암이냐 석회암이냐)를 할 땐 쓰지 마라.
**위에서 내려다본 공간 배치·동선**을 말하는 컷은 planline(평면 선화) — 검은 바탕에 흰 선
평면도. 방이 몇 개고 어떻게 이어지는지를 한눈에 보여줄 때만, 한 영상에 1컷이면 충분하다.
**작전·지형·건물 배치를 한눈에 놓고 볼 때**는 tabletop(미니어처 3D) — 매끈한 무광 축소 세계다.
한 색이 화면을 지배하고 발광 경로선·켜진 창만 대비로 남는다. 인물은 **얼굴이 없는** 미니어처다.
claysection 과 갈리는 지점: claysection 은 무채색 단면 모형(치수), tabletop 은 색이 있는 축소
세계(배치·경로). 이 톤은 카메라가 자동으로 묶인다(요소 개수가 바뀌면 바로 티가 나므로).
**대상 하나를 정면으로 소개하는 컷**(유물·조각·상징물·제품 하나)은 blackstage(심플 블랙) —
순수 검정 배경에 흰 무광 캐스트 하나, 시안 발광 곡선 하나만 대비로 남는다. 배경도 바닥도 없다.
훅에서 "이것이 무엇인가"를 던질 때, 또는 여운 컷에서 대상만 남길 때 강하다.
글자는 넣지 마라 — 이 톤의 라벨·제목은 편집에서 얹는다.
도시·지형·시설을 하늘에서 부감할 땐 aerial(실사 드론 항공).
**인물이 이야기를 끌고 가는 재연 컷**(역사적 사건의 재연, 썰쇼츠형의 인물 서사·감정 장면)은
**인물 3D 톤 셋 중 하나**를 골라라 — 이 셋과 anime 만 얼굴·표정이 나와도 된다.
· game    — 게임 엔진 실시간 캡처 룩(화면반사·블룸 같은 엔진 흔적이 정체성). 액션·전투·
            현장감이 요점일 때.
· story3d — 오프라인 렌더 3D 시네마틱. **영화 렌즈**가 정체성 — 얕은 심도, 색조 대비 조명,
            필름 그레인. game 과 달리 엔진 흔적이 없고 더 차분하다. **전쟁·사건 재현**에 강하다.
· whitecast — greycast 의 **밝은 짝**. 도로·건물·차를 흰 로우폴리 모형으로 지은 밝은 세계에서
            얼굴 없는 마네킹이 연기한다. greycast 와 갈리는 지점: **밝고**, 옷이 암시가 아니라
            **실제 형태**(전술조끼·정모·부츠, 단 무채색)이며, 총구 연기·파편 같은 굵은 입자가
            허용된다. **총격전·재난·사고처럼 공개된 사건의 액션**에 쓴다.
· greycast — **얼굴 없는 회색 마네킹**이 연기한다. 인물·소품·차·벽·천장까지 세계 전체가
            같은 무광 회색 각면이고, 세트 밖은 순수 검정이다. **얼굴이 아예 없어서 실존 인물을
            닮을 수가 없다** — 범죄·사건·근현대사처럼 실존 인물이 나오는 소재에 이걸 써라.
            이 톤의 장치 하나: **이야기의 대상 하나만 실제 질감**을 준다(지폐·문서·흉기).
            세계가 무표정하니 그 하나가 확 튄다 — subject_en 에 그 물건만 구체적으로 묘사하라.
· toy3d   — 통통한 미니어처 피규어가 연기한다(큰 머리·짧은 팔다리·무광 비닐, 입이 없고
            눈썹이 표정을 만든다). 조명만은 진지한 영화처럼 간다 — 그 낙차가 이 톤의 힘이다.
            **무거운 소재(전쟁·범죄·정치)를 톤을 낮춰 다루고 싶을 때.**
한 영상에서 인물 톤은 **하나로 통일**하라 — 셋을 섞으면 같은 인물이 딴사람처럼 보인다.
주인공은 뒷모습 어깨너머(OTS) 구도를 우선하고, 감정이 요점인 순간에만 정면·클로즈업을 써라.
시대 의상·소품·장소의 생활감을 subject_en 에 구체적으로 담아라. 실존 인물(왕·장군·근현대
유명인)은 어느 톤이든 실제 얼굴을 닮게 그리지 마라 — 매번 창작 얼굴로.
원리·구조 설명 컷에는 인물 톤을 쓰지 마라(그건 docu3d·tech3d).
장소가 주인공인 훅은 '위성 줌인' 패턴이 강하다: 훅 컷을 aerial 로 잡고 subject_en 에 위성·항공
시점을 명시한 뒤, 다음 컷을 chain=true 현장 컷으로 이으면 지도에서 현장으로 내리꽂는 오프닝이 된다.
속·단면을 갈라 원리를 증명하는 컷(층이 드러나고 안에서 무슨 일이 일어나는지)은 xsection(단면 실험).
힘·흐름·방향을 설명하는 컷은 subject_en에 glowing flow lines 또는 luminous arrows를 명시하라.
톤은 '주 톤 + 양념' 구조로 짜라. 영상 전체의 절반 안팎은 대표 톤(주로 docu3d)으로 밀어
채널 색을 유지하고, 나머지를 archive·snap·tech3d·illust 등으로 섞어 흐름에 변화를 준다.
대표 톤은 연속으로 와도 되지만, 보조 톤(archive·snap·illust 등)은 3연속으로 쓰지 마라.

[3-1. 홀로그램 재구성 — 카메라로 찍을 수 없는 것만 실사 현장 위에 겹쳐라]
실사 현장 위에 시안 홀로그램(와이어프레임 + 반투명 볼륨)을 겹쳐, 지금 그 자리에 없는 것을
재구성하는 연출이다. 별도 필드는 없다 — **subject_en 과 motion_en 에 직접 써넣는다.**
docu3d·arch3d·aerial·cine 톤의 현장 컷에서만 쓴다.
· **홀로그램은 반드시 subject_en 에 완성된 모습으로 써서 이미지에 굽는다.** 영상 모델이
  가는 와이어프레임을 새로 그리면 뭉개진다 — motion_en 은 점등·맥동·스캔·소멸처럼
  '이미 서 있는 홀로그램의 변화'만 시켜라. 무에서 조립되는 과정(assembles itself)은 금지.
  '나타나는 순간'이 필요하면 chain 을 써라: 앞 컷을 홀로그램 없는 같은 현장 실사로 잡고
  이 컷을 chain=true 로 이으면 앞 클립이 이 컷 이미지로 도착하며 홀로그램이 자연스럽게
  떠오른다 ([1]-3 묶음 규칙과 weather_en 동일 문구 규칙은 그대로 지켜라).
· 켜는 조건 — 대사가 다음 넷 중 하나를 말할 때만:
  ① 과거 재구성(사라진 구조물·원래 모습): beat=context·solution. 대사 신호 "원래는",
     "당시에는", "지금은 사라진".
     subject_en 예: "the surviving stone foundation of the ruined hall at dusk; above it, a
     translucent glowing cyan wireframe hologram of the vanished wooden superstructure stands
     reassembled in its original position, thin luminous edges and faint transparent volumes,
     while the real ruin and the landscape stay fully photoreal"
  ② 투시 재구성(숨은 내부·지하·가려진 구조): beat=constraint·solution. 대사 신호 "속에는",
     "벽 뒤에", "기초는", "땅속에". **'벽 안에 보인다'가 아니라 벽 위에 겹쳐 그린 투영이다**
     — 실물 벽은 끝까지 불투명하게 두어라 (껍질이 투명해지는 xray 와는 다른 연출이다).
     subject_en 예: "the massive stone facade fully opaque and photoreal; superimposed OVER it
     like a projection, a glowing cyan wireframe hologram of the hidden timber skeleton, drawn
     at the exact position and scale of the structure behind the wall"
  ③ 비교·대안(기각되는 뻔한 답, 만약 ~였다면): beat=constraint·pivot. 대사 신호 "그냥
     ~하면 되지 않냐", "~했다면 어땠을까". 대안 설계를 실물 옆에 홀로그램으로 세워 굽고,
     영상에서 **한 번에** 무너뜨려라 — 다단계 액션은 모델이 중간을 건너뛴다.
     motion_en 예: "the translucent cyan hologram of the conventional straight wall standing
     beside the real structure buckles and shatters into fading cyan fragments that dissolve
     in mid-air, while the real scene around it stays still and photoreal"
  ④ 스케일 비교(크기를 익숙한 것으로): beat=hook·context. 대사 신호 "아파트 ~층 높이",
     "축구장 ~개 넓이". 익숙한 사물의 홀로그램을 실물 옆에 실제 비율로 세운다.
     subject_en 예: "the real dam wall in morning haze; beside it a translucent glowing cyan
     wireframe hologram of a ten-storey apartment building stands at true scale for height
     comparison, thin luminous edges, the entire real landscape photoreal"
· motion_en 규칙 — 홀로그램 컷의 motion_en 은 **반드시 홀로그램을 언급**하고(언급이 없으면
  영상 모델이 지워버린다) 점등·맥동형으로 써라. 문장 끝에 이 고정 절을 그대로 붙여라:
  "while the real scene around it stays still and photoreal".
  motion_en 예: "the cyan wireframe hologram brightens to full presence, its edges pulsing
  gently and a faint scan shimmer passing across its translucent surfaces, while the real
  scene around it stays still and photoreal"
· 카메라가 격하면 헤어라인이 지글거린다 — 홀로그램 컷은 still·push·orbit 계열이 어울린다.
· 절대 끄는 조건: 실물로 그냥 찍으면 되는 대상(보이는 것을 홀로그램으로 또 그리지 마라),
  analogy(생활 비유)·closing(여운) 컷, 분위기·감정 컷,
  archive·snap·illust·labmacro·xsection·blueprint·tech3d·sci3d 톤.
· **다큐의 선 — 최우선 규칙.** 배경·지면·하늘·실물은 끝까지 100% 실사이고, 홀로그램은
  프레임 속 소수 요소 하나다. 화면 전체를 덮는 그리드·파티클·디지털 배경·홀로그램 도시
  전경은 금지 — 그 순간 다큐가 아니라 SF가 된다. 홀로그램이 화면의 주인이 되면 실패다.
· **한 영상에 최대 1~2컷, 연속 컷 금지.** 애매하면 쓰지 마라 — 실물이 이긴다.
· **홀로그램 컷은 focus_en 과 measure_en 을 반드시 빈 문자열로 둬라.** 홀로그램 자체가 이
  컷의 강조 장치다 — HUD·발광 주석까지 겹치면 두 벌 강조로 화면이 SF 광고가 된다.
· 홀로그램에도 글자·숫자는 금지. 순수한 선과 반투명 면만.

[4-a. focus_en — 주석이 가리킬 단 하나]
대사가 **무언가를 설명하는 컷**일 때만 채운다. 그 문장이 말하는 대상·현상 하나를 영어로.
**그 순간 대사가 "이걸 보라"고 말하는 바로 그 물체·부위여야 한다** — 화면에서 가장 큰 것도,
그 컷의 주인공 전체도 아니다. 대사가 "돌끼리 맞물린 부분"을 말하면 등대 전체가 아니라
맞물린 이음매 하나이고, "파도가 때리는 밑동"이면 탑이 아니라 밑동이다.
대사를 다시 읽고, 그 문장에서 시청자가 눈으로 확인해야 하는 것을 그대로 적어라.
분위기 컷(훅의 풍경, 감정, 마무리)은 빈 문자열 — 주석 없이 깨끗한 화면이 낫다.
예외: 훅에서 숫자 하나가 결정적일 때(예: "20km나 떨어진")는 focus_en 과 measure_en 을
함께 채워라 — 첫 2초에 숫자가 박히면 시청자를 잡는다.
홀로그램 재구성 컷([3-1])과 그래픽 애니메이션을 붙인 컷([4])은 반드시 빈 문자열 —
강조 장치는 컷당 하나다. 홀로그램·그래픽 위에 주석을 또 얹지 않는다.
**한 영상에서 3~4컷만 채워라.** 매 컷 강조가 켜지면 그건 강조가 아니라 배경이고, 시청자
시선이 대사가 아니라 화면 여기저기의 HUD 를 따라다닌다. 대사가 물체를 콕 집어 설명하는
컷만 남기고 나머지는 비워라. 채우지 않은 컷에는 주석이 그려지지 않는다.
**개수는 네가 지켜라 — 앱의 상한은 기본이 '제한 없음'이라 네가 켠 대로 전부 나간다.**
(사용자가 상한을 켜두면 넘긴 만큼 **뒤쪽 컷부터** 꺼진다 — 후반의 회수 컷이 가장 먼저 죽는다.
 그러니 **뒤에서부터 예약하라**: solution·pivot 에서 반드시 살릴 컷 1~2개를 먼저 정하고
 남은 자리를 앞쪽에 배분하라. 훅 근처에 3개를 몰지 마라.)
**beat=hook 컷의 강조는 measure_en 이 있거나 anno_kind=glow 일 때만 화면에 나온다.**
훅에 scale·versus·arrow 같은 도구를 쓰려면 measure_en 을 반드시 함께 채워라 —
안 채우면 focus_en 과 anno_kind 가 멀쩡해도 주석이 통째로 꺼진다.
(closing 컷은 예외가 없다 — 여운이 목적이라 무엇을 채워도 꺼진다)

[4-b. measure_en — 화면에 새길 수치]
대사에 숫자가 나오고 그게 **이 컷의 요점**일 때만 채운다 (예: "20km나 떨어진" → "20km",
"46년을 버텼는데" → "46Y", "40분이면 다 타서" → "40min", "두 개씩 붙어" → "x2").
분위기·감정 컷이나 숫자가 곁가지면 빈 문자열. 한 영상에서 3~5컷을 넘지 않게 아껴 써라 —
전부 붙이면 정보 과잉이 된다.
**중요: measure_en 은 focus_en 이 채워진 컷에만 넣어라.** 수치는 주석 치수선 위에 얹히므로
가리킬 대상이 없으면 화면에 나오지 않고 버려진다. 숫자를 새기고 싶으면 focus_en 도 채워라.
마무리(closing) 컷은 여운이 목적이라 수치를 넣어도 화면에 안 나온다 — 넣지 마라.

[4-d. anno_kind · anno_label — 강조를 무엇으로 그릴까]
focus_en 을 채운 컷에만 정한다 (비운 컷은 둘 다 빈 문자열).

**도구 고르기 전 3초 점검 — 이 순서로 물어라:**
① **화면이 이미 말하고 있나?** motion·subject 가 그 정보를 직접 실연하면(끼우는 손,
   미는 손, subject 에 이미 그려진 경로·도해) 방향 도구(arrow·flow·route)는 금지다 —
   손과 화살표가 같은 자리를 다투고 같은 말을 두 번 한다. 이런 컷은 지목 도구
   (spotlight·glow)로 대상만 짚어라.
② 요점이 **수치·양**인가 → measure·gauge·count·graph
③ 요점이 **"이것"의 위치·존재**인가 → glow·outline·spotlight·marker
④ 요점이 **범위·구조**인가 → zone·extent·void·skeleton·bracket
⑤ 요점이 **움직임·힘의 경로**인가 (①에 안 걸릴 때만) → arrow·flow·route·trajectory·
   wave·loadsplit·spin
⑥ 헷갈리면 끄지 말고 **폴백 사다리로 켜라** — 강조는 시선을 잡는 후킹 장치다:
   대상이 면·구역이면 **zone**, 형태 있는 물체면 **glow**, 어두운 장면에서 하나를
   골라내는 거면 **spotlight**. 단 ①의 중복만은 피하라.

**강조는 "이걸 보세요"가 아니라 "이게 이렇게 됩니다"를 그리는 것이다.** 그 컷 대사가 말하는
논리에 맞는 도구를 골라라 — 레퍼런스 채널이 실제로 쓰는 다섯 가지다:

· arrow  — 움직임·경로·방향을 **한 방향**으로 말할 때. **가장 많이 쓰는 도구다.**
           "물이 지하수까지 차오릅니다" / "물길을 이쪽으로 돌립니다" / "여기로 빠져나갑니다"
· void   — **비어 있는 공간 자체가 주인공**일 때. 방·널방·통로·빈 틈의 모양을 반투명 부피로
           채워 보여준다. glow 는 물체 표면에 달라붙는 도구라 빈 공간엔 못 쓴다.
           "이 안이 통째로 비어 있습니다" / "천장 위에 방이 다섯 개 더 있죠" /
           "이 벽 속에 사람이 지나갈 통로가 있습니다"
           · focus_en 은 그 빈 공간 하나를 영어로 (예: "the hollow burial chamber above the
             ceiling"). 컷당 하나만 — 여러 방을 동시에 채우면 어디를 보라는 건지 갈린다.
· route  — **사람·물건이 지나간 길**. flow 와 나누는 기준은 '무엇이 지나가는가'다:
           힘·물·공기·열이면 flow, 사람·시신·행렬·방문객이면 route.
           "왕의 시신은 이 통로로 들어갔습니다" / "순례자는 여기서 저기까지 돌았죠"
· flow   — 눈에 안 보이는 것이 **어디서 나와 무엇을 지나 어디서 끝나는지** 여정 전체를
           말할 때 (힘·하중·물·공기·열·전기·연료). arrow 와의 갈림길은 **출발지와 도착지가
           둘 다 대사의 핵심인가**다 — 방향 하나면 arrow, 여정이면 flow.
           "지붕 하중이 기둥을 타고 기초까지 내려갑니다" / "바깥 공기가 좁은 통로를 지나
            안쪽으로 빠집니다" / "열이 이 금속을 타고 바깥 날개까지 퍼집니다"
           · focus_en 에 **여정 전체를 한 구로** 적어라 — 출발·경로·도착이 다 들어가야 한다
             (예: "load transfer from the roof beam down the stone column into the foundation").
             흐름의 띠 그림은 시스템이 알아서 그린다 — subject_en 에 또 쓰지 마라(두 벌이 된다).
           · 한 컷에 흐름은 **하나만**. 물과 공기를 같이 그리면 무엇을 보라는 건지 갈린다.
           · measure_en 은 비워라 (수치가 요점이면 flow 가 아니라 measure 컷이다).
· reject — 안 되는 방법·실패·금지를 말할 때. beat=constraint·despair 와 짝이 맞는다.
           "그렇게는 안 됩니다" / "5년 만에 통째로 쓸려갔죠" / "이 방법은 못 씁니다"
· zone   — 부위 하나가 아니라 **구역·범위**를 통째로 말할 때.
           "이 일대가 전부 잠깁니다" / "여기가 지반이 약한 구간입니다"
· gauge  — **비율·성능·차오름**. 퍼센트나 정도를 말할 때 (measure_en 에 % 나 수치 필수).
           "60퍼센트가 코를 푼다고 답했죠" / "압력이 두 배까지 올라갑니다"
· scale  — **크기가 안 와닿을 때** 익숙한 것과 나란히 놓는다. compare_en 필수.
           "80톤짜리 돌입니다" → compare_en: three full-size cargo trucks parked in a row
           수치가 크고 추상적일수록 measure 보다 이쪽이 낫다.
· marker — **여러 지점을 동시에** 찍을 때. 한 곳이면 zone·glow 를 써라.
           "이 부분마다 열이 걸립니다" / "곳곳이 갈라져 있습니다"
· count  — marker 와 같은데 **총계를 함께** 보여준다. measure_en 에 개수를 넣어라(x30, 30p).
           "안에 삼십 명이 숨어 있었죠" / "삼십 세대가 동시에 돌아갑니다"
           개수 자체가 놀라움의 근거일 때 쓴다. 수치가 없으면 marker 와 같아진다.
· spotlight — 대상만 밝히고 주변을 어둡게. **작거나 배경이 복잡해 윤곽선이 안 읽히는** 자리.
           "저 사람이 범인이었습니다"(군중 속 하나) / "이 부품 하나가 문제였죠"(더미 속 하나)
           outline 이 '선으로 감싸기'라면 이건 '빛으로 골라내기'다.
           인물을 지목할 때는 대부분 이쪽이 낫다 — 사람은 윤곽이 복잡해 선이 지저분해진다.
· extent — **화면 밖까지 이어지는 긴 것 하나**를 길이 전체에 걸쳐 발광시킨다.
           "철조망은 수용소를 통째로 둘러쌌습니다" / "이 배관이 건물 끝까지 갑니다"
           요점이 **얼마나 멀리 가느냐**일 때 쓴다. 울타리·담·터널·도로·배관·철로.
           기둥처럼 반복 요소가 있으면 전부 같은 발광 블록으로 통일된다.
           glow 가 덩어리 하나(기념물·건물)라면 이건 **선으로 뻗은 것**이다.
· graph  — **정량 관계를 곡선으로**. "깊을수록 강하다", "갈수록 빨라진다"처럼 한 값이
           구조물을 따라 변하는 것이 요점일 때. 축+눈금+곡선+옅은 워시가 구조물 위에
           원근을 따라 그려진다. 수치·라벨 없이 형태만으로 읽히므로 measure_en 은 비운다.
           "수압은 깊이에 비례합니다" / "포탄은 포신을 지나며 계속 빨라집니다"
· spin   — **축을 도는 회전** 하나. 강선 회전·모터·터빈·드릴·선회.
           나선이 회전축을 두세 바퀴 감고 화살촉이 방향을 가리킨다.
           "포탄은 회전하며 안정을 얻습니다" / "이 축이 분당 천이백 번 돕니다"
· wave   — **한 점에서 퍼지는 것**. 충격파·폭발·음파, 그리고 몸속에서 **번지는** 것
           (감염·약물 확산). 원점에서 동심 링 서너 개가 지면을 따라 타원으로 기울며 퍼진다.
           "포구를 떠나는 순간 충격파가 퍼집니다" / "삼십 분 만에 온몸으로 퍼지죠"
· skeleton — **실물 속에 숨은 부재망**을 겹쳐 보인다. 돔의 리브, 다리의 트러스,
           몸속 혈관망·신경망. 반복 부재가 한 시스템으로 읽히게 같은 굵기로 그려지고,
           앞쪽 부위에 가려지는 원근을 지킨다. "이 몸을 지탱하는 건 이 관들입니다"
· loadsplit — **한 힘이 갈라져 우회**하는 경로. 아치·삼각공간·교량 설명의 핵심.
           들어온 하중이 분기점에서 두 갈래로 갈라져 양쪽 부재를 타고 내려가고,
           **피해 가는 구역은 완전히 비워 둔다**. "무게가 문을 누르지 않고 비켜 갑니다"
· trajectory — **공중 포물선** 하나. 발사점 점 → 정점 → 착탄점 화살촉 + 지면 링.
           탄도·투척·낙하. focus_en 에 발사점과 착탄점을 **한 구 안에 함께** 써라
           (예: the shell arc from the muzzle to the impact point on the far slope).
           **궤적은 이 강조가 그린다 — subject_en 에 아크·경로 선·궤적 도해를 함께
           묘사하지 마라.** 둘 다 그리면 화면에 궤적이 겹으로 생긴다 (강조 장치는 컷당 하나).
· versus — **알려진 것과 실제가 다를 때** 화면을 위아래로 갈라 둘을 나란히 세운다.
           compare_en(위·널리 알려진 모습) + focus_en(아래·실제 모습) 둘 다 필수.
           "다들 대리석인 줄 알지만, 사실은 벽돌에 회칠을 한 겁니다"
             compare_en: the temple front as everyone pictures it, solid white marble blocks
             focus_en:   the same front actually built of brick with a thin plaster skin
           **반전을 말로 설명하는 대신 보여주는 자리다.** 오해를 짚는 컷이면 이걸 우선하라.
           **anno_label 은 빈 문자열로 두어라 — 분할 비교는 글자 없이 간다.**
           위/아래를 가르는 이름표("MYTH / REALITY")는 굽지 않는다. 굽힌 글자는 편집에서
           못 고치고, 라벨 상자가 화면 위쪽을 잡아먹어 정작 비교할 그림이 밀린다.
           필요하면 편집에서 자막으로 얹는다. **두 면의 차이가 그림만으로 안 읽히면
           그 컷은 실패한 것이다** — 글자로 때울 자리가 아니라 compare_en·focus_en 을
           더 또렷하게 갈라 쓸 자리다.
           카메라는 자동으로 고정된다(화면을 가른 구도라 시점이 바뀌면 깨진다).
           **한 통념은 한 번만 기각한다.** 앞 컷에서 홀로그램([3-1]③)으로 이미 무너뜨렸다면
           여기서 또 뒤집지 마라 — 시청자는 이미 답을 들어서 회수가 반복이 된다.
           앞 컷에서는 통념을 **세우기만** 하고, 기각은 이 컷 한 번만.
· crack  — 균열·손상을 그 선을 따라 그릴 때. "천장에 금이 가 있습니다"
· bracket— 화면의 한 영역을 ⌐ ¬ 로 지목. zone 과 달리 **네 모서리만** 표시한다.
· outline— **여러 개 중 이것**을 가리킬 때. 치수가 아니라 위치를 말하는 컷.
           "가장 큰 게 쿠푸 왕의 것입니다" — 셋 중 하나를 윤곽선으로 특정
· measure— 치수·수치·계측. measure_en 이 있고 끝점([4-e])을 줄 수 있으면 이것.
           (옛 이름 hud 도 그대로 받는다 — 같은 도구다)
           "높이가 45m입니다" / "두께 3.5m로 쌓았죠"
· glow   — 와이드·항공에서 구조물 **전체**를 지목할 때. 부분 설명에는 쓰지 마라.

anno_label 은 그 대상의 짧은 영문 이름이다. **한 단어를 기본으로 하고, 두 단어는 한 단어로는
뜻이 안 통할 때만** 쓴다 — 글자가 짧을수록 안 뭉개지고 화면도 덜 복잡해진다.
  좋음: Latch · Gasket · Void · Beam · Khufu · Core
  두 단어가 필요한 경우: Relief Chamber · Gable Cap
  **공백 포함 16자 이내.** 넘으면 앱이 첫 단어만 남겨 뜻이 깨진다
  ("Relieving Chamber"(17자) → 화면에는 "Relieving" 만 새겨진다)
  나쁨: The Bronze Latch(관사) · Bronze Latch Mechanism(설명) · Hidden Troop Inside(문장)
**기본은 빈 문자열이다.** 아래 셋 중 하나에 해당할 때만 채워라 —

  ① 이름을 알아야 설명이 이해될 때        "청동 빗장이 걸려 있습니다" → Bronze Latch
  ② 전문 용어를 처음 소개할 때            "무게경감의 방입니다" → Relief Chamber
  ③ 비슷한 것이 여러 개라 구분이 필요할 때  세 피라미드 중 하나 → Khufu

반대로 **강조 도구가 이미 말하고 있으면 붙이지 마라.** 라벨까지 얹으면 과하다.
  "이 방법은 안 됩니다"      reject 의 X 가 이미 말한다      → 빈 문자열
  "물이 여기로 흐릅니다"      flow 의 띠가 이미 말한다        → 빈 문자열
  "이 구역이 위험합니다"      zone 의 경계가 이미 말한다      → 빈 문자열
  "저 목마입니다"            화면만 봐도 안다               → 빈 문자열

**한글은 쓰지 마라** — AI 가 글자를 뭉갠다. 마땅한 영어 이름이 없어도 빈 문자열이다.
라벨은 이미지에만 새겨지고 영상은 그것을 그대로 유지한다.
한 영상에서 2~3컷을 넘기지 마라 — 글자가 늘수록 화면이 복잡해지고 뭉개질 확률도 올라간다.

[4-c. chars — 이 컷에 나오는 인물 (anime 톤 전용)]
작품요약형(C)에서만 채운다. 캐릭터 시트의 라벨 **한 글자**를 배열로: ["A"], ["A","B"] 처럼.
그 컷에 실제로 프레임 안에 있는 인물만 적어라 — 한 컷에 셋을 넘기지 마라(작게 뭉개진다).
인물이 안 나오는 컷(텅 빈 코트, 전광판, 배경만)은 빈 배열.
**이름을 쓰지 마라** — 시트에는 A·B·C·D 라벨만 있어서 이름으론 누구인지 못 짚는다.
같은 인물은 영상 내내 같은 라벨이어야 한다. 라벨 배정은 첫 등장 순서대로 A부터.
anime 가 아닌 톤에서는 항상 빈 배열.

[4-c. weather_en — 날씨·대기 (사실감 레이어)]
현장(야외·실물 공간) 컷에 채운다 — 공기 중에 보이는 것을 영어 짧은 구로.
(예: "dry heat haze, fine sand dust drifting low" / "cold sea spray and storm wind" /
 "thin morning mist hanging over the water" / "dust motes in shafts of light")
· 대본에 단서(폭풍·비·사막·바다·겨울…)가 있으면 반드시 그걸 따르라.
· 단서가 없으면 장소와 이야기 정서에 어울리는 것 **하나만** 골라라.
· **같은 현장을 보여주는 컷들은 전부 같은 대기를 그대로 복사해 써라** — 특히 chain 묶음은
  동일 문구여야 한다. 컷마다 날씨가 바뀌면 한 장소가 여러 장소처럼 보인다.
· **단, 같은 장소라도 '시점'이 다르면 다른 대기다.** 지금 남아 있는 모습과 과거 재현,
  공사 전과 후는 같은 문구를 쓰지 마라 — 쓰면 수백 년의 시간 간격이 화면에서 지워진다.
  **한 축만 바꿔라**(빛 하나 또는 대기 하나). 전부 바꾸면 다른 장소가 된다.
    현재: "low sea wind with thin salt haze, cold flat daylight"
    과거: "low sea wind with thin salt haze, warm low dawn light"
· **바꿨으면 되돌아오지 마라.** 맑음 → 비 → 맑음처럼 오가면 한 장소가 여러 날처럼 보인다.
  조건부 장면(비가 와도, 밤에도)은 영상 뒤쪽에 몰아라.
· 시간대(새벽·한낮·노을·밤)는 별도 필드가 없다 — 대본에 단서가 있을 때만 이 필드에 함께
  녹여라 (예: "golden late-afternoon light through drifting dust"). 단서가 없으면 넣지 마라.
· 스튜디오·도해·자료화면 컷(labmacro·blueprint·illust·xsection, screen 샷)은 빈 문자열.

[4. motion_en]
모든 컷에 채운다 — 시간에 따라 무엇이 변하는지 영어 한 문장.
hook 은 가장 극적으로(화면 전체가 변하는 큰 움직임). solution 은 발광·흐름이 이동하는 과정으로.
카메라 움직임은 쓰지 마라(카메라는 따로 정한다).
**인물 톤(game·story3d·toy3d·greycast·whitecast) 컷은 동작을 작게 잡아라.**
· 시킬 수 있는 것 — **자세 하나**: 몸을 낮추며 총을 든다 · 고개를 든다 · 팔을 뻗는다 ·
  한 걸음 내딛는다 · 무릎을 꿇는다. 시작과 끝이 눈에 보이게 다르되 **동작은 하나**다.
· 시키지 마라 — 여러 걸음 걷기·달리기, 두 사람이 동시에 다른 동작, 격투·난투.
· **인물이 셋 이상이거나 화면에서 작게 잡힌 컷은 아무도 움직이지 마라.** 자세를 잡은 채로
  두고 카메라만 움직여라 — 모델이 작은 실루엣을 프레임마다 다시 그려 형태가 뭉개지고
  인원수가 바뀐다. **부감·와이드로 여럿을 보여주는 컷은 카메라도 고정하라.**
  (실측 2026-08-15, whitecast 4초 오빗: **크게 잡힌 2명은 자세·인원·얼굴 없음까지 완전히
   유지**됐고, 중간 거리 4명은 형태가 흐물거리며 시키지 않은 연기가 생겼으며,
   부감 8명은 인물이 사라졌다 나타나고 배치가 프레임마다 재구성됐다)
· 인물이 셋 이상인데 화면이 움직여야 하면 **카메라를 아주 조금만** 움직여라
  (slowpush·slowslide). 크게 도는 오빗이 붕괴의 방아쇠였다.
· 화면이 변해야 하는데 인물이 못 움직이면, **카메라와 그래픽이 변화를 맡는다** — 그게 정상이다.
  (레퍼런스 실측 2026-08-15, 8컷 전수: 인물이 실제로 이동하는 컷은 25%뿐이고
   나머지는 카메라가 물러나거나·훑거나, 화면의 수치·치수선이 자라났다)
**글자 없는 그래픽 애니메이션** — 도형만으로 된 HUD 를 컷에 얹을 수 있다.
**반드시 두 곳에 나눠 쓴다**: 도형의 완성된 모습은 subject_en 에 써서 2K 이미지에 굽고,
motion_en 에는 **이미 있는 그 도형의 변화**만 적는다. 영상 모델이 가는 선을 새로 그리면
뭉개진다([5-3]) — 홀로그램과 같은 원리다([3-1]).

**subject_en 에 붙이는 그래픽 구는 반드시 이 말로 시작하라 —
`already drawn as a flat cyan graphic overlay,`
(이 문구로 시스템이 그래픽 컷을 알아본다. 빠뜨리면 강조가 두 벌로 겹친다)**

어울리는 컷과 문형:
  · 한계·누적·정도를 말하는 컷(주로 constraint)
    subject_en 끝: "; already drawn as a flat cyan graphic overlay, a thick cyan arc gauge
      beside the structure, its full track clearly visible with a short filled portion
      near its start"
    motion_en 끝: "; the bright fill along the already visible cyan arc advances once
      toward its limit and holds"
  · 조사·분석·측량을 말하는 컷(pivot·solution)
    subject_en 끝: "; already drawn as a flat cyan graphic overlay, a wide soft cyan scan
      band lying across the structure, the surface beneath it glowing faintly"
    motion_en 끝: "; the wide soft cyan scan band travels once across the structure and
      fades, the surface returning to a steady glow"
  · 면적·범위·부지를 말하는 와이드·항공 컷
    subject_en 끝: "; already drawn as a flat cyan graphic overlay, a coarse cyan survey
      grid laid across the ground, thick lines following the terrain in perspective"
    motion_en 끝: "; a single bright front travels once across the already visible cyan
      grid, then it returns to a steady glow and holds"
  · 배수·비교("3배", "절반")를 말하는 컷
    subject_en 끝: "; already drawn as a flat cyan graphic overlay, two thick cyan bars
      standing side by side on the ground at clearly different heights"
    motion_en 끝: "; the two already visible cyan bars brighten once from base to tip and hold"

규칙: ① 한 컷에 하나만, 한 영상 2~3컷까지 — 전부 붙이면 계기판이 된다.
② 도형뿐이다 — 글자·숫자·눈금 라벨은 여기서도 금지.
③ 이 그래픽을 붙인 컷은 focus_en·measure_en 을 **반드시** 비워라 — 강조 장치는 컷당 하나다.
   어기면 이미지에 구운 도형 위에 주석이 또 얹혀 화면이 계기판이 된다.
   수치 자체가 요점인 컷은 그래픽 대신 기존 방식(focus_en + measure_en)을 써라.
④ 홀로그램 재구성 컷([3-1])에는 덧붙이지 마라. ⑤ docu3d·aerial·arch3d 톤에서만
   (tech3d 는 발광 강조가 이미 하나 있어 겹치면 두 벌이 된다).
⑥ **위 문구를 그대로 복사하지 마라** — 문형 견본이지 완성 문장이 아니다. 대상·배치를
   이 컷에 맞게 새로 써라. 그대로 쓰면 편마다 같은 화면이 나온다.
⑦ **motion_en 은 반드시 그 도형을 이름으로 다시 언급하라**("the already visible cyan
   arc / band / grid / bars"). 언급이 없으면 영상 네거티브가 "요구하지 않은 HUD"로 판정해
   **시작 프레임에 구운 도형을 지운다** — 홀로그램의 motion_en 규칙([3-1])과 같은 이유다.

[4-e. from_en · to_en — 선이 어디서 어디까지인가]
**anno_kind 가 measure · arrow · flow · route 이면 반드시 둘 다 채워라.** 이 넷은 두 점을 잇는
도구다. 끝점이 없으면 모델이 축을 찍는다 — 실측(2026-08-12): 대회랑 '높이'를 물었는데
통로 **폭**에 43m 를 붙였고, 하중 화살표는 좌우로 갈라지는 핵심을 못 그려 설명이 뒤집혔다.
끝점을 주자 같은 톤·같은 골격에서 전부 바로잡혔다.

위 넷 외에는 **전부 빈 문자열이다 — 채워도 앱이 버린다.**
reject·zone·glow·extent·graph·wave·skeleton·loadsplit·trajectory·spin·void·gauge·scale·versus·marker·count·spotlight·crack·bracket·outline 은
한 점·한 영역·한 쌍을 가리키는 도구라 끝점이 필요 없다.

쓰는 법: 화면에서 **눈에 보이는 자리**를 적는다. 추상적인 개념이 아니라 그 컷에 실제로
찍혀 있는 표면·모서리·부위여야 한다.

  measure "천장이 43m 위에 있는데"
        from_en: the polished floor slab at the bottom of the gallery
        to_en:   the topmost corbel course of the ceiling
  arrow "하중이 좌우로 갈라져 벽으로 빠집니다"
        from_en: the stone mass pressing down from above
        to_en:   the thick side walls that take the load
  flow  "바깥 공기가 좁은 통로를 지나 안쪽으로 들어옵니다"
        from_en: the narrow intake vent on the outer wall
        to_en:   the room on the inner side
  route "왕의 시신은 이 통로로 들어갔습니다"
        from_en: the entrance shaft on the north face
        to_en:   the burial chamber deep inside

나쁜 예: from_en 에 "the ceiling"(어느 점인지 없음), "cold air"(자리가 아니라 대상),
"the beginning"(추상). 한쪽만 채우면 둘 다 무시된다.

[4-g. scene_ko — 파일명이 되는 짧은 이름]
**앞 12자만 파일명에 남는다.** 그 12자 안에 '무엇이 찍혔는가'가 들어가야 한다.
피사체를 맨 앞에, 카메라·시간·수식은 뒤로. 15자 내외 명사구로 끝내라.
  좋음: "이음매 클로즈업" · "쓰러진 상 밑동" · "클레이 단면, D자 밑면"
  나쁨: "새벽 해안 제단 위에 홀로 선 모아이를 올려다보는 저각 와이드"
        (파일명에 남는 건 "새벽 해안 제단 위에 홀" — 무엇이 찍혔는지 안 보인다)
**subject_en 은 어떤 경우에도 비우지 마라** — 비면 이 한글 문장이 영어 프롬프트 자리로
들어가 이미지가 통째로 어긋난다.
검수 메모·판단 근거를 여기 쓰지 마라 — 그건 검수_ko 에 쓴다.

[4-h. 검수_ko — 사람이 붙여넣기 전에 읽는 한 줄]
모든 컷에 채운다. **무엇을 찍는지가 아니라 무슨 판단을 했는지**를 적어라 —
화면을 정하는 값이 전부 영어라, scene_ko 만 읽어서는 판단 오류가 안 보이기 때문이다.
형식: [톤/화각] · [무엇을] / 캐논: [대상, 주의점] / 강조: [도구와 이유] / [이어짐] / 대기
  예: "docu3d/wide · 구덩이 rim, 아직 미굴착 / 캐논: 구덩이 — 주의: 캐논에 H기둥이
       들어 있는데 이 시점엔 아직 없다 / 강조 없음 / 단독 컷 / 대기: 오후 맑음"
  예: "docu3d/close · 젖은 이음매 클로즈업 / 캐논: 등대(화각 때문에 재질만 사용)
       / 강조: 이음매를 measure 로, 3.5m / 앞 컷에서 이어짐 / 대기: 폭풍"
**이 줄은 영어 필드를 요약한 것이다. 둘이 다르면 영어 필드가 틀린 것이다.**
이 필드는 앱이 읽지 않는다 — 사람 눈에만 보인다. 영어로 쓰지 마라.
이 줄만 위에서 아래로 훑으면 톤 분배·강조 예산·체인 흐름이 한눈에 보여야 한다.

[4-i. sound_en — 이 컷에서 나는 소리]
효과음을 켠 배치에서만 쓰인다. 꺼져 있으면 무시되므로 늘 채워도 손해가 없다.

**화면에 보이는 것이 내는 소리만 적어라.** 돌이 갈리면 갈리는 소리, 밧줄이 당겨지면
삐걱이는 소리다. 분위기 형용사("장엄한", "긴장감 있는")는 소리가 아니다.

  좋음: thick rope creaking under load, timber levers groaning, stone grinding into chalk
  좋음: one heavy stone impact into turf, then dust settling and wind over grass
  나쁨: dramatic tension, epic atmosphere        ← 소리가 아니다
  나쁨: narrator explains the mechanism          ← 대사는 절대 금지

**음악·대사·나레이션·군중 웅성거림은 쓰지 마라.** 우리는 나레이션을 따로 얹기 때문에
사람 목소리가 섞이면 그 클립은 못 쓴다. (앱이 금지문을 덧붙이지만 여기서도 쓰지 마라)

소리가 뚜렷하지 않은 컷 — 도해·클레이 모형·정지 전경 — 은 **빈 문자열**로 두어라.
억지로 채우면 없던 소리가 생긴다.

[5. 원리·구조를 보여주는 컷의 추가 규칙]

[5-1. 인과는 한 단계만 — motion_en 공통 규칙]
영상 모델은 한 클립에 사건을 여러 개 시키면 **중간을 건너뛴다** (A→B→C 를 시키면 A→C 가 나온다).
그러니 motion_en 에는 **원인 하나와 거기 직접 반응하는 결과 하나**만 적어라.
  형태: "[A 의 동작], [B 의 직접 반응]"
  좋은 예: "the piston drives downward, turning the connected crankshaft through one partial rotation"
  나쁜 예: "the piston drops, turns the crankshaft, spins the gear train and drives the wheel"
  좋은 예: "the inlet valve swings open, releasing one continuous stream of water into the outlet pipe"
  나쁜 예: "the valve opens, water fills the chamber, the float rises and the outlet closes"
· "then / and then / after that / next / finally" 로 사건을 이어 붙이지 마라.
  (단 "…before it settles" 처럼 **한 동작이 끝나며 가라앉는 마무리**를 적는 건 사건이 아니다 — 괜찮다)
· 대사가 A→B→C 를 다 설명하더라도, 이 컷의 요점에 가장 직접 답하는 **한 고리**만 영상화한다.
  나머지는 ①시작 이미지에 이미 그 상태로 그려두거나 ②같은 공간이면 다음 chain 컷으로 넘겨라.

[5-2. 분해뷰 — 부품·내부 구획이 어떻게 맞물리는지 보여줄 때]
기계·제품뿐 아니라 **건축물·유적의 내부 구획**에도 쓴다 (피라미드의 널방·통로·하중경감석,
성벽의 안팎 겹, 배의 갑판 층). 켜는 조건 — 대사가 다음 중 하나를 말할 때만:
  ① 무엇으로 이루어져 있는가 ② 어디에서 맞물리는가 ③ 어떤 순서로 쌓이는가
  ④ 핵심 부분이 전체 어디에 있는가
속이 보이기만 하면 되는 컷은 분해뷰가 아니라 xsection(단면)·cutaway 를 써라.
· **분해된 상태를 subject_en 에 완성된 모습으로 적어 이미지에 굽는다.** 반드시 영어로
  "shown in a compact exploded view" 라는 말을 넣어라 (이 문구로 시스템이 분해뷰 컷을 알아본다).
· 전부 벌리지 말고 **대사가 말하는 덩어리만** 벌려라. 각 조각은 조립됐을 때의 방향을 그대로
  유지한 채 제 자리에서 **실제 조립 방향으로 조금씩만** 떨어져 있어야 하고, 원래 실루엣이
  한눈에 읽혀야 한다. 작은 부속(못·쐐기·꺾쇠)은 따로 띄우지 말고 붙여둬라 — 720p 에서 뭉개진다.
· motion_en 은 **직선 재조립 한 번**이 기본이다 (분해 후 재조립을 한 클립에 같이 시키지 마라):
  예: "the separated chambers and passage blocks slide straight back along their own stacking
       axes until every stone seats into place"
· 분해뷰 자체가 강조 장치다 → focus_en·measure_en·anno_kind·anno_label 은 **전부 빈 문자열**.
  홀로그램·HUD·화살표를 같은 컷에 겹치지 마라.

[5-3. 720p 영상이 그릴 수 있는 것 / 없는 것 — motion_en 어휘]
**가늘거나 개수가 많은 것을 영상이 새로 그리면 뭉개진다.** 필요한 그림은 2K 이미지에 굽고,
영상에는 '이미 있는 것의 변화' 하나만 맡겨라.
· 영상에 맡겨도 되는 것: 이미 있는 굵은 화살표·띠 위를 지나가는 **밝은 앞머리 하나**,
  이미 있는 발광의 **밝기 변화**, 단단한 부품의 **직선 이동**, 큰 껍질 하나가 **투명해지는 것**,
  넓고 부드러운 **스캔 띠**, 개수가 적고 큼직한 입자.
· 영상에서 새로 그리게 하지 마라: 가는 발광선, 와이어프레임, 글자·숫자·라벨,
  고체를 통과하며 속을 만들어내는 절단면, 가는 스캔선, 물체 윤곽을 일그러뜨리는 아지랑이,
  갈래치는 번개·자가 작도되는 회로, 수천 개의 미세 입자, 반복 화살표·갈매기표, 동시에 두 흐름.
· 바꿔 쓰는 법: 가는 스캔선 → "넓고 부드러운 스캔 띠가 한 번 지나간다" /
  열 아지랑이 → "표면에 넓은 열 색 영역이 퍼진다" / 갈래 번개 → "이미 있는 굵은 경로 위로
  밝은 펄스가 한 번 지나간다" / 공기 입자 → "넓은 반투명 공기 띠가 밀도파를 한 번 실어 나른다"
· 공통 문형: "already visible" (이미 있다) · "stays fixed / locked in perspective" (고정된다)
  · "a single bright front travels once" (앞머리 하나가 한 번 지나간다)
  · "returns to a steady glow and holds" (지나간 뒤 은은하게 유지된다)

[5-4. reveal — 속을 어떻게 열어 보일까]
대부분의 컷은 **빈 문자열**이다. 대사가 내부·구조·속을 실제로 설명할 때만 고른다.
· partial_cutaway — **기본값으로 먼저 검토하라.** 외벽 일부만 열어 내부를 보이고 나머지 외형은
  그대로 둔다. **외형 자체가 상징인 대상**(피라미드·목마·성벽·탑)은 통째로 자르면 시청자가
  "이게 뭐였지"를 잃는다. 겉과 속을 한 화면에서 같이 읽히게 하는 게 이 방식의 값어치다.
· breakout — 관심 부위 한 군데만 창처럼 파낸다. 부분절개보다 더 국소적. 이음매·결합부·
  균열처럼 **작은 한 곳**을 볼 때.
· full_section — 통째로 관통해 자른다. 층 구조·내부 배치를 **전부 한 번에** 보여야 할 때만.
· ghosted — 외형을 반투명으로 남기고 내부를 선명하게. 내부 위치 관계를 설명할 때.
  (실물 벽 위에 홀로그램을 겹치는 [3-1]② 와 다르다 — 이건 대상 자체가 반투명해진다)
· layer_reveal — 겉껍질 한 겹만 들어낸다. "겉은 석회암, 속은 화강암" 처럼 층을 말할 때.
· stack_split — **층·단으로 쌓인 것을 수직으로 띄운다.** 건물 층뿐 아니라 배 갑판·지층·
  필터 단·서버 랙에도 쓴다. 축이 하나라 원래 실루엣이 그대로 읽힌다 —
  분해뷰([5-2])는 여러 방향으로 벌어져 형태가 흩어지지만 이건 위아래로만 벌어진다.
  "몇 층인지 · 층마다 무엇이 있는지 · 어떤 순서로 쌓였는지"를 말할 때.
· xray — **유일하게 자르지 않는 리빌.** 껍질을 그대로 두고 밀도로 속을 비춘다.
  나사·배선·뼈대·빈 공간처럼 **재질 차이가 요점**일 때. ghosted 와 갈리는 지점:
  ghosted 는 내부가 '실물'로 보이고, 이건 방사선 사진처럼 밝기 계조로만 읽힌다.
규칙 ① **리빌 컷 수는 대본 형식([0])을 따른다 — 하나의 숫자로 묶지 마라.**
· **원리 분석형(A)** — 건축물·무기·기계·제품이 "어떻게 되어 있나"를 다루는 대본에서는
  **자르는 것이 본론이다.** 한 영상의 **1/3까지** 리빌을 써도 된다. 구조를 설명하는 대사가
  이어지면 연달아 쓰는 것도 맞다. 아껴 쓰다가 말로만 설명하고 넘어가는 게 더 큰 손해다.
· **사건 서사형(B)·작품요약형(C)** — **0~2컷.** 자르는 순간 이야기가 도해로 식는다.
  인물·사건이 끌고 가는 대본에서 단면은 흐름을 끊는다.
· 어느 형식이든 **자를 이유가 없는 컷은 자르지 마라** — 훅의 풍경, 생활 비유, 여운 컷.
  리빌은 "대사가 속을 설명할 때" 붙는 것이지 화면을 화려하게 하는 장치가 아니다.
② **shot 에 'cutaway' 를 쓰지 마라 — reveal 을 비워도 앱이 전체 단면으로 읽어, 네가 세지
   않은 리빌 컷이 하나 더 생긴다.** 속을 여는 것은 언제나 reveal 로만 말하고, shot 에는
   화각만 적어라 (wide/close/macro/pov/object/screen).
   **style=xsection 컷은 reveal 이 비어 있어도 '연 컷'으로 세어라** (①의 2~3컷 예산에 포함).
③ 같은 대상을 연속으로 다르게 자르지 마라 — 부분절개로 열었으면 다음 컷은 그 안을 보여준다.

[5-5. evidence — 아는 것과 추정한 것을 구분한다 (문화유산 컷)]
사라진 구조물·유적의 원형을 그리는 컷에서만 채운다. 그 외에는 **빈 문자열**.
· solid — 지금도 남아 있는 것만 보여주는 컷. 실사 그대로.
· inferred — 근거는 있으나 복원한 부분이 섞인 컷. 대사 신호 "~로 추정됩니다", "~였을 겁니다".
· hypothetical — 확실치 않은 가설을 그리는 컷. 대사 신호 "밝혀지지 않았습니다", "가설입니다",
  "아무도 모릅니다". 복원부가 와이어프레임으로만 나와 **가설임이 화면에 드러난다.**
이 필드의 목적은 장식이 아니라 **정직함**이다. 모르는 것을 아는 것처럼 그리면 콘텐츠의 신뢰가
깨진다 — 모르면 모른다고 그려라. 대사가 단정하지 않는 자리에 hypothetical 을 쓰면
"이건 추측입니다"를 말로 하지 않고도 화면이 대신 말해준다.

[출력]
아래 JSON만 출력. 설명·마크다운·코드펜스 금지.

**글자 수 상한 — 넘으면 앱이 조용히 자른다. 처음부터 이 안에서 써라.**
  focus_en 140 · from_en/to_en 각 90 · compare_en (scale 90 / versus 110)
  measure_en 12 (라틴 문자·숫자만 — 한글은 통째로 지워진다: "46년" → "46")
  anno_label 16 (넘으면 첫 단어만 남는다) · scene_ko 는 앞 12자가 파일명이 된다

{{
  "title": "이 영상의 짧은 제목",
  "product_hint": "다루는 제품·대상의 한글 일반명사",
  "format": "explainer | story",
  "cuts": [
    {{
      "no": 1,
      "line": "이 컷이 깔릴 대사 원문 그대로",
      "scene_ko": "파일명이 되는 짧은 한글 이름 — 앞 12자 안에 '무엇이 찍혔나'가 들어가야 한다. 15자 내외 명사구. [4-g] 참고",
      "검수_ko": "사람이 눈으로 검수할 한글 한 줄 — 무슨 판단을 했는지. [톤/화각] · [무엇을] / 캐논: [대상, 주의점] / 강조: [도구와 이유] / [이어짐] / 대기. [4-h] 참고",
      "beat": "hook | context | constraint | despair | pivot | solution | analogy | closing",
      "type": "product | principle | analogy | context | usage | reaction",
      "style": "docu3d | tech3d | sci3d | arch3d | snap | cine | archive | illust | labmacro | blueprint | aerial | xsection | claysection | planline | tabletop | blackstage | game | story3d | toy3d | greycast | whitecast | anime — **이 목록에 없는 값을 지어내지 마라. 앱이 조용히 snap(폰카 스냅샷)으로 바꿔 톤이 통째로 어긋난다.** 목록에 없는 느낌이 필요하면 가장 가까운 값을 골라라 — 미니어처·축소 세계는 tabletop, 무채색 단면 모형은 claysection, 테이블 위 실물 시연은 labmacro",
      "shot": "화각·배치만 정한다 — macro | wide | close | pov | object | screen. 현장 액션·풍경은 wide/close, 1인칭 시점은 pov. **속을 여는 것은 shot 이 아니라 reveal 이다**",
      "reveal": "속을 어떻게 열어 보일지 — \\"\\"(안 자름) | partial_cutaway | breakout | full_section | ghosted | layer_reveal | stack_split(층·단을 수직으로 띄움) | xray(안 자르고 밀도로 비침). 대부분의 컷은 빈 문자열. [5-4] 참고",
      "evidence": "문화유산 복원 컷에서만 — \\"\\"(해당 없음) | solid(현존) | inferred(근거 있는 추정) | hypothetical(가설). [5-5] 참고",
      "chain": "앞 컷과 같은 장소·같은 피사체를 이어서 보여줄 때만 true (묶음의 첫 컷은 false). **anno_kind 를 채운 컷은 반드시 false** — 카메라가 다음 장면으로 이동하는 동안 강조가 화면 밖으로 밀려난다. 설명 컷은 단일로, 이어짐은 강조 없는 이동 컷에",
      "subject_en": "무엇이 찍혔는지 영어로 구체적으로. 재질·색·상태까지. 반복 등장 피사체는 [1]-7 의 캐논 문구를 앞머리에 그대로 복사해 시작하라. type=product 여도 채워라 (AI 생성 가능해야 한다).",
      "place_en": "장소 영어. 없으면 빈 문자열",
      "search_ko": "type=product 일 때만 실물 검색어. 아니면 빈 문자열",
      "motion_en": "영상화 시 무엇이 변하는지 영어 한 문장. product 도 채워라. 인과는 한 단계만 — [5-1] 참고",
      "sound_en": "이 컷에서 **무슨 소리가 나는지** 영어로 짧게 (예: thick rope creaking under load, stone grinding into chalk). 화면에 보이는 것이 내는 소리만 — 음악·대사·나레이션은 절대 쓰지 마라(앱이 따로 금지한다). 장면에 뚜렷한 소리가 없으면 빈 문자열. 120자 이내. 라틴 문자만. [4-i] 참고",
      "focus_en": "이 컷에서 화면 주석이 가리켜야 할 **단 하나**를 영어로 짧게. 대사가 설명하는 바로 그것 (예: 'the wave force slamming into the tower base', 'how the two dovetail blocks lock together', 'water seeping down through the sand layers'). 가리킬 게 없거나 분위기·감정 컷이면 반드시 빈 문자열 — 그러면 주석을 아예 안 그린다",
      "measure_en": "이 컷 대사에 '핵심 수치'가 있을 때만 화면에 새길 짧은 라틴 표기. 한글 단위는 반드시 영문/기호로 바꿔라 — 년→Y(46Y), 시간→H(7H), 분→min(40min), 개→x(x2), 배→x(3x), 원→KRW(300KRW), 명→p, 도→°C. 길이·무게는 그대로(20km, 150cm, 12t). 12자 이내. 수치가 없거나 이 컷의 요점이 아니면 반드시 빈 문자열",
      "weather_en": "현장 컷의 날씨·대기 영어 구 (같은 현장 컷들은 동일 문구). 스튜디오·도해 컷은 빈 문자열",
      "chars": "anime 톤(작품요약형)에서만 — 이 컷에 나오는 캐릭터 시트 라벨 배열 (예: [\\"A\\",\\"B\\"]). 그 외 톤이거나 인물이 없으면 빈 배열",
      "anno_kind": "이 컷의 강조를 무엇으로 그릴지 — measure | outline | spotlight | arrow | flow | route | gauge | scale | versus | marker | count | crack | bracket | reject | zone | void | glow | extent | graph | wave | skeleton | loadsplit | trajectory | spin. focus_en 이 비면 빈 문자열. [4-d] 참고",
      "flow_of": "anno_kind 가 flow 일 때만 — 무엇이 흐르는지: cold_air | warm_air | heat | water | force | electricity | smoke | blood. 색이 여기서 정해진다 (찬 공기는 하늘색, 열은 주황). 그 외에는 빈 문자열",
      "compare_en": "anno_kind 가 scale 또는 versus 일 때만. scale 이면 크기를 가늠할 익숙한 비교 대상 (예: three full-size cargo trucks parked in a row). versus 면 위 칸에 들어갈 '널리 알려진 모습' 을 focus_en 과 같은 문장 형식으로 (예: the temple front as everyone pictures it, solid white marble blocks). 그 외에는 빈 문자열",
      "from_en": "**두 점을 잇는 도구(measure·arrow·flow·route)에서만** — 그 선이 시작하는 지점을 영어로 (예: the polished floor slab at the bottom, the stone mass pressing from above). reject·zone·glow 이거나 anno_kind 가 비면 빈 문자열. [4-e] 참고",
      "to_en": "위와 짝 — 그 선이 끝나는 지점 (예: the topmost corbel course, the thick side walls that take the load). 한쪽만 채우면 둘 다 무시된다",
      "anno_label": "강조 옆에 새길 짧은 영문 라벨 (예: Bronze Latch, Relieving Chamber). 대문자로 시작하는 1~2단어. **기본은 빈 문자열** — 이름을 알아야 설명이 이해되거나, 전문 용어를 처음 소개하거나, 비슷한 것 여럿을 구분할 때만 채운다. 강조 도구가 이미 말하고 있으면(X·띠·영역) 붙이지 마라. 한 영상 2~3컷까지. 한글 금지 — AI가 뭉갠다. [4-d] 참고"
    }}
  ]
}}

[대본]
{script}
"""

# ── 🔬 원본 분석 — 컷 프레임 3장(시작·중간·끝)을 보고 제작 방식을 역설계한다 ──
# 목표는 '설명'이 아니라 '재현' — 우리 앱의 프리셋 id 로 답하게 해서 그대로 옮길 수 있게 한다.
ANALYZE_PROMPT = """너는 AI 영상 제작 감독이다. 아래 이미지는 한 컷에서 뽑은 **시작·중간·끝 3프레임**을
가로로 이어 붙인 것이다 (왼쪽=시작, 오른쪽=끝). 이 컷이 **어떻게 만들어졌는지 역설계**하라.
프레임 간 차이가 곧 카메라 움직임과 피사체 변화의 증거다. 이 컷의 길이는 약 {secs}초다.

[중요] 설명이 아니라 **재현**이 목적이다. 아래 보기 중에서 골라라. 보기에 없으면 가장 가까운 것.

style (톤): docu3d(현장에 선 시네마틱 다큐 3D·필름 그레인) | tech3d(3D 인포그래픽·무채색+발광)
 | sci3d(포토리얼 3D·미시/단면) | arch3d(3D 렌더 전경)
 | snap(폰카 스냅) | cine(시네마틱) | archive(빈티지 흑백) | illust(플랫 일러스트)
 | labmacro(어두운 테이블 실물 시연) | xsection(잘라서 속을 보여주는 단면 실험) | aerial(실사 드론 항공)
 | blueprint(네이비 청사진 도해)
 | game(AAA 게임 컷신 — 얼굴 허용) | anime(단순 플랫 만화 — 작품요약형 전용, 얼굴 허용)

camera: push(다가감) | pull(물러남) | down | up | panright | panleft | pushdown(다가가며 하강)
 | pullup(물러나며 상승) | orbit(공전) | still(고정) | sweeparc(좌우 빠른 아크) | crash(돌진줌)
 | whip(휩팬) | whiptilt | fpv(드론 슉슉) | dollyzoom | roll | chase | handheld | riseorbit | hyperlapse

motion_kind: assemble(자가조립) | disassemble | exploded | morph | grow | collapse | crack | erode
 | burn | age | flood | seep | pour | cure | dissolve | crystal | cutaway | xray | flow | heat
 | timelapse | holo(홀로그램 점등) | hud(글자 없는 HUD 도형) | subtle(미세한 움직임만) | none(정지에 가까움)

shot: macro | cutaway | wide | close | pov | object | screen
beat: hook | context | constraint | despair | pivot | solution | analogy | closing

[출력] 아래 JSON만. 설명·마크다운 금지.
{{
  "scene_ko": "이 컷이 무엇을 보여주는지 한 문장",
  "style": "위 보기 중 하나",
  "style_why": "그 톤이라고 본 근거 (질감·조명·배경 특징)",
  "color": "색감 한 줄 — 지배색과 그레이딩 (예: 무채색 청회색 + 빨강 포인트)",
  "texture": "질감 한 줄 — 3D 렌더인지 실사인지, 표면 디테일",
  "light": "조명 한 줄 — 방향·경도·시간대",
  "composition": "구도 한 줄 — 중앙대칭/삼분할, 피사체 크기, 여백",
  "shot": "위 보기 중 하나",
  "camera": "위 보기 중 하나",
  "camera_why": "프레임 간 무엇이 달라져서 그렇게 봤는지",
  "motion_kind": "위 보기 중 하나",
  "motion_desc": "피사체가 시작→끝으로 어떻게 변했는지 한 문장",
  "beat": "위 보기 중 하나",
  "graphics": "화면에 얹힌 그래픽 — 없으면 'none'. 있으면 종류(치수선/화살표/발광선/라벨/자막)와 색",
  "graphics_source": "ai_baked(이미지에 그려짐·화면과 함께 움직임/글자 깨짐) | edited(편집 오버레이·선명하고 고정) | none",
  "people": "인물 처리 — 없음 | 얼굴 노출 | 얼굴 안 보임(손·뒷모습·실루엣)",
  "ai_made": "이 컷이 AI 생성으로 보이는가 — yes | no | unclear",
  "ai_why": "그 판단의 근거 (AI 특유의 흔적 또는 실사 증거)",
  "reproducible": "우리 앱으로 재현 가능한가 — easy | medium | hard",
  "repro_note": "재현 시 주의점 (실물 소스 필요, 편집 그래픽 필요 등)",
  "subject_en": "이 컷을 다시 만들기 위한 영문 이미지 프롬프트 한 문장 (재질·색·상태까지 구체적으로)",
  "motion_en": "영상화용 영문 모션 문장 한 문장 (카메라 언급 금지, 무엇이 변하는지만)",
  "sound_en": "이 컷에서 나는 소리 영어로 짧게 (없으면 빈 문자열)"
}}"""

# ── ✂ 자막 재분할 — 타입캐스트가 준 문장 단위 SRT 를 쇼츠 화면폭에 맞게 쪼갠다 ──
# 어절(띄어쓰기) 경계를 지키고, 의존명사·조사로 줄이 시작하지 않게 앞말과 붙인다.
SUB_GLUE = ("것", "게", "걸", "거", "수", "때", "줄", "뿐", "데", "지", "등", "만큼", "대로",
            "채", "척", "터", "바", "적", "듯", "만", "년", "월", "일", "시", "분", "초",
            "개", "명", "번", "원", "미터", "킬로", "센티",
            # 수량 단위 — "한 / 방울도" 처럼 수사와 떨어지면 의미가 안 읽힌다 (2026-08-11)
            "방울", "가지", "마리", "장", "켤레", "그루", "송이", "덩어리", "톨", "쪽", "칸")
# 뒷말과 **함께 넘어가야** 하는 어절. SUB_GLUE 는 앞말에 붙이는데 이쪽은 방향이 반대다 —
# 부정어·관형어는 뒤에 오는 말을 꾸미므로 혼자 줄 끝에 남으면 의미가 끊긴다
# ("안 / 들어가" 는 읽는 순간 뜻이 뒤집힌다, "군용 / 포장" 은 한 덩어리가 갈라진다).
SUB_LEAD = ("안", "못", "잘", "더", "덜", "다", "또", "곧", "막", "갓", "새", "온", "전",
            "그", "이", "저", "한", "두", "세", "네", "첫", "매", "약", "총", "단")
# 의존명사가 어미와 붙어 길어진 형태 — "거였는데?"(5자)는 3자 제한에 걸려 줄 첫머리로
# 밀려났다 ("만든 / 거였는데?", 2026-08-11 제보). 제한을 그냥 늘리면 "게임"(게+임)·
# "수요일"(수+요일)·"데이터"(데+이터)까지 붙으므로, **어미를 구체적으로 못박아** 잡는다.
SUB_GLUE_LONG = re.compile(
    r"^(거|것|게|걸|줄|수|때)(였|이었|이야|이죠|이지|이라|이란|예요|입니다|이다|인데|라고|뿐|만큼)")
# 의존명사·단위가 **어절 전체**이거나 조사만 붙은 형태 ("게", "년을", "개가").
# startswith 로 판단하면 "원래"(원)·"만든"(만)·"데이터"(데)·"지금"(지)·"바로"(바)·"터널"(터)
# 까지 앞말에 붙어버린다 — 3자 이하 조건으로는 못 막는다 (2026-08-11 실측:
# 이 오탐 때문에 "그 봉지가 원래" / "나가려고 만든" 이 한 덩어리가 됐다).
SUB_GLUE_RE = re.compile(
    r"^(것|게|걸|거|수|때|줄|뿐|데|지|등|만큼|대로|대신|다음|뒤|후|전|채|척|터|바|적|듯|만"
    r"|년|월|일|시|분|초|개|명|번|원|미터|킬로|센티|방울|가지|마리|장|켤레|그루|송이)"
    r"(까지|밖에|처럼|보다|부터|마다|에서|으로|은|는|이|가|을|를|에|의|도|만|과|와|랑|나|야|씩)?"
    r"[.,?!…\"')]*$")     # 문장부호가 붙어도 같은 어절이다 ("거." 가 혼자 남지 않게)


def is_sub_glue(w):
    """이 어절을 앞말에 붙여야 하는가 — 의존명사·단위 단독/조사형, 또는 어미가 붙은 긴 형태."""
    return bool(SUB_GLUE_RE.match(w) or SUB_GLUE_LONG.match(w))
# 낭독의 쉼이 이 값을 넘으면 문장 경계로 본다. 실측(2026-08-11): 같은 문장 안 단어 간격은
# 중앙값 0.04초, 문장 경계는 0.2~0.8초였다. 0.25는 그 사이에서 안전한 쪽으로 잡은 값 —
# 낮추면 절 중간에서도 끊기고, 높이면 두 문장이 한 줄에 남는다.
SUB_GAP_SPLIT = 0.25
# 이 길이 이하의 빈 구간은 앞 자막을 늘려 메운다(fill_gaps). 문장 사이의 한 박자 쉼까지
# 메우면 이미 끝난 말이 다음 문장 직전까지 남아 어색하므로 그보다 짧은 쪽만 손댄다.
SUB_FILL_MAX = 0.5
SUB_PUNCT_W = {",": 0.12, "·": 0.08, ".": 0.25, "?": 0.28, "!": 0.28, "…": 0.3}


def srt_time(sec):
    sec = max(0.0, float(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s - int(s)) * 1000)):03d}"


def srt_parse(txt):
    """SRT/VTT 를 [{start, end, text}] 로. 번호·형식이 조금 달라도 살려낸다."""
    out = []
    txt = (txt or "").replace("\r\n", "\n").replace("﻿", "")
    pat = re.compile(r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3})")

    def _sec(s):
        s = s.replace(",", ".")
        h, m, rest = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)

    blocks = re.split(r"\n\s*\n", txt.strip())
    for b in blocks:
        m = pat.search(b)
        if not m:
            continue
        body = b[m.end():].strip()
        body = re.sub(r"\s*\n\s*", " ", body).strip()
        if body:
            out.append({"start": _sec(m.group(1)), "end": _sec(m.group(2)), "text": body})
    return out


# 타임코드 없는 대본을 넣었을 때 쓰는 추정치. 한국어 나레이션 실측 기준
# (타입캐스트 기본 속도에서 공백 제외 5글자/초 안팎). 정확한 값은 아니고 초안용이다.
SUB_CPS = 5.0        # 초당 글자 수
SUB_SENT_GAP = 0.28  # 문장 사이 숨


def clean_script_lines(txt):
    """대본을 낭독 줄로 나눈다. **붙여넣은 것을 전부 읽는다** — 빈 줄만 버린다.

    예전엔 앞머리의 화자 이름·제목을 자동으로 뺐다(타입캐스트에서 복사하면 딸려오던 것).
    그런데 훅 첫 줄이 원래 짧고 마침표 없이 끝나서 같은 모양이라, **대본 첫 문장이 통째로
    안 읽히는 사고**가 났다 (2026-08-19: "최악의 발명품 소리 듣던 그 신발").
    자동 판별로는 둘을 못 가른다 → 사용자가 안 읽을 줄을 지우고 넣기로 결정 (같은 날).
    반환: (lines, dropped) — dropped 는 항상 빈 목록이다(호출부 호환용).
    """
    lines = [ln.strip() for ln in (txt or "").replace("\r\n", "\n").split("\n")]
    return [ln for ln in lines if ln], []


def line_bounds(lines):
    """대본 줄들이 '몇 번째 글자에서 끝나는지' 누적 위치 집합. 공백은 세지 않는다 —
    TTS 가 돌려주는 단어 텍스트와 대조해야 하는데 띄어쓰기가 서로 다를 수 있다."""
    out, n = set(), 0
    for ln in (lines or []):
        n += len(re.sub(r"\s+", "", ln))
        if n:
            out.add(n)
    return out


SUB_PUNCT_RE = re.compile(r"[\s.,!?~…\"'“”‘’·:;()\[\]<>]")


def cues_from_chunks(words, chunks):
    """이미 나눠 둔 자막 조각에 단어 타임스탬프를 얹는다.

    타입캐스트 단어는 입력 순서 그대로 오므로, 부호·공백을 뺀 글자수를 누적하면
    어느 단어에서 조각이 끝나는지 정확히 찾을 수 있다 (_line_spans 와 같은 방식).
    대본과 발화가 어긋나 매칭이 깨지면 빈 목록을 돌려 호출부가 폴백하게 한다."""
    cues, wi, n = [], 0, len(words)
    for ch in chunks:
        text, eol = (ch if isinstance(ch, tuple) else (ch, False))
        need = len(SUB_PUNCT_RE.sub("", text))
        if need <= 0:
            continue
        got, st, en = 0, None, None
        while wi < n and got < need:
            t = SUB_PUNCT_RE.sub("", words[wi].get("text") or "")
            if not t:                     # 부호만 있는 토큰은 건너뛴다
                wi += 1
                continue
            if st is None:
                st = float(words[wi]["start"])
            en = float(words[wi]["end"])
            got += len(t)
            wi += 1
        if st is None:
            break                         # 단어가 먼저 떨어졌다 — 남은 조각은 시각을 못 준다
        # eol = 대본 줄의 마지막 조각. 음슴체는 마침표가 없어 부호로는 문장 끝을 알 수 없으므로
        # 이 표시가 있어야 뒤 공정이 다음 문장 첫 어절을 끌어다 붙이지 않는다.
        cues.append({"start": round(st, 2), "end": round(en, 2), "text": text, "eol": eol})
    if wi < n and cues:                   # 남은 발화는 마지막 줄이 물고 간다 (자막이 먼저 끝나지 않게)
        cues[-1]["end"] = round(float(words[-1]["end"]), 2)
    return cues


def words_to_cues(words, max_chars=10, min_dur=0.7, gap_split=SUB_GAP_SPLIT, lines=None):
    """단어별 타임스탬프(실측)를 화면폭에 맞는 자막 줄로 묶는다.

    글자 수로 시간을 나누는 추정과 달리 **각 줄의 시작·끝이 실제 발화 시각**이다.
    줄을 끊는 규칙은 sub_chunks 와 같다 — 어절 경계를 지키고, 의존명사는 앞말에,
    부정어·관형어는 뒷말에 붙이며, 종결부호 뒤를 우선 분할점으로 쓴다.

    여기에만 있는 단서가 하나 더 있다: **낭독의 쉼**. 음슴체 대본("~거", "~고", "~림")은
    마침표가 없어서 부호로는 문장 경계를 못 찾는다. 그런데 사람은 문장 끝에서 숨을 쉰다 —
    실측(2026-08-11): 같은 문장 안 단어 간격은 중앙값 0.04초인데 문장 경계는 0.2~0.8초였다.
    그래서 gap_split 이상 쉬면 거기서 끊는다. 이게 없으면 "실어버린 거 비결은 성분이"처럼
    한 줄에 두 문장이 섞인다.
    """
    # 대본이 있으면 **글로 먼저 나누고** 시각을 얹는다. 단어를 앞에서부터 훑으며 10자에서
    # 끊는 방식은 앞뒤를 못 보므로 "백 도가 / 넘는 압력솥에"처럼 꾸미는 말이 갈라진다.
    # sub_chunks 는 문장 전체를 보고 절·구 경계에서 고르게 나눈다 — 텍스트 재분할과 같은 엔진이다.
    if lines:
        # 어절마다 '그 뒤의 쉼'을 붙여 준다. 대본 어절과 발화 단어는 띄어쓰기가 다를 수 있어
        # 글자수를 누적해 맞춘다 — 어긋나면 gaps 를 버리고 문법 규칙만으로 나눈다.
        gaps, wi, n = [], 0, len(words)
        for ln in lines:
            for w in ln.split():
                need, got_n, last_end = len(SUB_PUNCT_RE.sub("", w)), 0, None
                while wi < n and got_n < need:
                    t = SUB_PUNCT_RE.sub("", words[wi].get("text") or "")
                    if t:
                        got_n += len(t)
                        last_end = float(words[wi]["end"])
                    wi += 1
                nxt = float(words[wi]["start"]) if wi < n else last_end
                gaps.append(max(0.0, (nxt or 0.0) - (last_end or 0.0)))
        gaps_ok = wi >= n          # 대본 어절이 발화 단어를 빠짐없이 덮었을 때만 믿는다
        chunks, gi = [], 0
        for ln in lines:
            ws = ln.split()
            cs = sub_chunks(ln, max_chars, gaps[gi:gi + len(ws)] if gaps_ok else None)
            gi += len(ws)
            chunks += [(c, i == len(cs) - 1) for i, c in enumerate(cs)]
        got = cues_from_chunks(words, chunks)
        if len(got) >= max(1, len(chunks) - 1):    # 매칭이 어긋나면 아래 방식으로 폴백
            return got

    cues, cur, st, en = [], "", None, None
    pend = None          # 부정어·관형어 — 뒤 단어와 함께 넘어가야 한다 ("안 / 들어가" 방지)
    prev_end = None
    # 대본 줄 경계 = 사람이 직접 그은 문장 경계. 부호·쉼 추측보다 정확하므로 최우선이다
    bounds, seen_ch = line_bounds(lines), 0

    def flush():
        nonlocal cur, st, en
        if cur:
            cues.append({"start": round(st, 2), "end": round(en, 2), "text": cur})
        cur, st, en = "", None, None

    for w in words:
        t = (w.get("text") or "").strip()
        if not t:
            continue
        ws, we = float(w["start"]), float(w["end"])
        # 뒷말과 붙일 어절은 붙잡아 뒀다가 다음 단어와 한 덩어리로 처리한다
        if pend:
            t, ws = pend[0] + " " + t, pend[1]
            pend = None
        elif t in SUB_LEAD:
            pend = (t, ws)
            continue
        # 낭독의 쉼 = 문장 경계 (부호가 없는 음슴체 대본의 유일한 단서)
        if cur and prev_end is not None and ws - prev_end >= gap_split:
            flush()
        prev_end = we
        cand = (cur + " " + t).strip()
        glue = cur and is_sub_glue(t)
        if cur and len(cand) > max_chars and not glue:
            flush()
            cur, st, en = t, ws, we
        else:
            cur, en = cand, we
            if st is None:
                st = ws
        # 종결부호(. ? ! …)면 길이와 무관하게 끊는다. **두 분기 모두에서** 확인해야 한다 —
        # 폭이 넘쳐 새 줄로 넘어간 어절이 종결 어절인 경우(위 if 분기)를 빠뜨리면
        # 그 어절이 다음 문장을 끌어와 "나왔습니다. 그래서 거꾸로" 가 된다 (2026-08-10 제보).
        # 짧아서 읽기 힘든 줄은 sub_resplit 의 병합 단계가 앞줄과 합쳐준다.
        seen_ch += len(re.sub(r"\s+", "", t))
        if seen_ch in bounds:          # 대본에서 줄이 끝난 자리 — 무조건 끊는다
            flush()
        elif cur.endswith((".", "?", "!", "…")):
            flush()
        elif cur.endswith(",") and len(cur) >= max_chars * 0.5:
            flush()
    if pend:                      # 대본이 그 어절로 끝났다 — 버리면 글자가 사라진다
        cur = (cur + " " + pend[0]).strip()
        if st is None:
            st = pend[1]
        en = en if en is not None else pend[1]
    flush()
    # 너무 짧게 스치는 줄은 다음 줄이 시작되기 전까지만 늘린다 (겹치면 캡컷에서 깨진다)
    for i, c in enumerate(cues):
        if c["end"] - c["start"] < min_dur:
            limit = cues[i + 1]["start"] if i + 1 < len(cues) else c["start"] + min_dur
            c["end"] = round(min(max(c["end"], c["start"] + min_dur), limit), 2)
    return cues


def script_to_blocks(txt, cps=SUB_CPS, gap=SUB_SENT_GAP):
    """타임코드가 없는 순수 대본 → 문장 블록. 길이는 글자 수로 **추정**한다.

    타입캐스트에서 SRT 대신 대본을 복사해 오는 경우가 잦다. 거절하는 대신
    초안을 만들어 주고, 타이밍이 추정이라는 사실을 호출부가 알리게 한다.
    반환: (blocks, dropped) — dropped 는 화자 이름·제목으로 보고 뺀 줄들.
    """
    lines, dropped = clean_script_lines(txt)
    sents = []
    for ln in lines:
        # 한 줄에 문장이 여럿이면 종결부호 뒤에서 나눈다 (부호는 앞 문장에 남긴다)
        for s in re.split(r"(?<=[.?!…])\s+", ln):
            s = s.strip()
            if s:
                sents.append(s)
    blocks, t = [], 0.0
    for s in sents:
        n = len(re.sub(r"\s+", "", s))
        dur = max(0.9, round(n / max(1.0, cps), 2))
        blocks.append({"start": round(t, 2), "end": round(t + dur, 2), "text": s})
        t += dur + gap
    return blocks, dropped


def scale_blocks(blocks, total):
    """추정 타임라인을 실제 음성 길이(total 초)에 비례해서 늘리거나 줄인다.

    타입캐스트는 음성 속도를 조절할 수 있어서 글자 수만으로는 절대 못 맞춘다.
    하지만 **총 길이 하나만 알면** 비율로 맞출 수 있고, 문장별 오차는 글자 수 비례로
    남아 실제와 꽤 가깝다. 속도 설정을 몰라도 되는 게 요점이다.
    """
    if not blocks or not total or total <= 0:
        return blocks
    cur = float(blocks[-1]["end"])
    if cur <= 0:
        return blocks
    k = float(total) / cur
    return [{"start": round(b["start"] * k, 2), "end": round(b["end"] * k, 2),
             "text": b["text"]} for b in blocks]


# 끊기 좋은 자리 — 조사·연결어미로 끝나는 어절 뒤. 한국어는 여기가 의미 단위(구·절)의
# 경계라 읽는 사람의 호흡과 맞는다 ("상온에 / 일 년을 / 굴려도" 처럼).
# 이게 없으면 폭만 보고 채워서 "상온에 일 년을 / 굴려도 멀쩡한 은박" 처럼 구가 뭉갠다.
# 연결어미 — 절이 끝나는 자리다. 조사보다 훨씬 강한 경계라 여기서 먼저 끊어야
# "있는데 / 방부제가" 처럼 절 경계를 넘어 붙는 일이 없다.
# ── 끊어 읽는 자리 ────────────────────────────────────────────────
# 한국어는 어미·조사가 문법 경계를 표면에 그대로 드러낸다. 형태소 분석기 없이도
# 어절 끝만 보면 절·구 경계를 대부분 집어낼 수 있다.
#
#   절 경계(STRONG) — 연결어미. "굴려도 /" "팔려고 /" "죽고 /" 처럼 여기서 반드시 끊는다.
#   구 경계(OK)     — 조사. "상온에 /" "방부제가 /" 처럼 끊어도 좋은 자리.
#   그 외           — 조사도 어미도 없이 끝난 어절 = 뒷말을 꾸미는 수식어다.
#                     "은박 / 봉지가", "군용 / 포장을" 처럼 가르면 안 된다.
SUB_BREAK_STRONG = re.compile(
    r"(고|며|면|서|다가|는데|은데|지만|니까|아서|어서|거나|든지|려고|러|도록|자|듯"
    r"|[아어여]도|더니|면서|자마자|길래|느라|는지|든가)"
    r"[.,!?…\"')]*$")
# 접속부사 — 앞 문장을 받아 다음 이야기를 여는 말이라 뒤에서 끊으면 호흡이 산다
# ("근데 / 이 군용 포장을"). 어미가 없어 위 규칙엔 걸리지 않으므로 따로 둔다.
SUB_CONJ = {"근데", "그런데", "그래서", "그러니까", "그리고", "하지만", "그러나", "그럼",
            "즉", "결국", "게다가", "심지어", "따라서", "그러다", "그러자", "반면"}
# 조사 — 구가 끝나는 자리. 절 경계보다는 약하지만 폭만 보고 채우는 것보단 낫다.
SUB_BREAK_OK = re.compile(
    r"(에|에서|에게|으로|로|을|를|이|가|은|는|도|만|과|와|랑|의|께|한테|보다|처럼|까지|부터|마다|채|대로)"
    r"[.,!?…\"')]*$")


def _is_adnom(w):
    """관형사형 어미(-ㄴ/-는/-ㄹ/-던)로 끝나는가 — 뒤에 오는 명사를 꾸미는 말이다.

    같은 '꾸미는 말'이라도 관형절("만들어낸 / 군용 포장")은 끊어도 읽히는 반면,
    명사 수식어("군용 / 포장")는 가르면 말이 토막난다. 둘을 구분해 벌점을 달리 준다."""
    w = (w or "").rstrip(".,!?…\"')")
    if not w:
        return False
    ch = w[-1]
    if ch in "는던":
        return True
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 in (4, 8)    # ㄴ · ㄹ 받침
    return False


def _wrap_balanced(words, max_chars, gaps=None):
    """어절들을 max_chars 이내 줄로 나누되 **줄 길이를 고르게** 만든다 (word-wrap DP).

    탐욕(최대한 채우다 넘치면 끊기)은 줄 끝에 수식어를 홀로 남긴다 —
    "찾다가 만들어낸 군용 / 포장이었고" 처럼 '군용 포장'이 갈라진다 (2026-08-11 제보).
    같은 줄 수라면 길이 편차가 작은 쪽이 항상 읽기 좋으므로 편차의 제곱합을 최소화한다.
    → "찾다가 만들어낸 / 군용 포장이었고"

    한 어절이 max_chars 를 넘으면 그 어절만 한 줄로 둔다 (자를 수는 없다).
    """
    n = len(words)
    if not n:
        return []
    # cost[i] = words[i:] 를 나눴을 때의 최소 비용, nxt[i] = 그때의 다음 줄 시작
    INF = float("inf")
    cost, nxt = [INF] * (n + 1), [n] * (n + 1)
    cost[n] = 0.0
    for i in range(n - 1, -1, -1):
        ln, cross = -1, 0
        for j in range(i, n):
            ln += len(words[j]) + 1
            # 줄 안에 절 경계(연결어미)가 들어 있으면 절을 가로질러 붙인 것이다.
            # 보너스만으로는 못 막는다 — 폭을 꽉 채운 줄은 벌점이 0 이라 보너스가 무의미해서
            # "있는데 / 방부제가" 가 "있는데 방부제가" 로 붙어버렸다 (2026-08-11).
            if j > i and SUB_BREAK_STRONG.search(words[j - 1]):
                cross += 1          # 어절 + 공백 하나
            if ln > max_chars and j > i:     # 한 어절만으로 넘치면 어쩔 수 없이 허용
                break
            slack = max_chars - ln
            # 마지막 줄은 짧아도 자연스럽다 — 남는 자리에 벌점을 주지 않는다
            pen = 0.0 if j + 1 == n else slack * slack
            # 조사·연결어미로 끝나는 자리는 의미 단위 경계다 — 짧아도 여기서 끊는 게 낫다.
            # 벌점을 크게 깎아 "상온에 / 일 년을 / 굴려도" 처럼 구 단위로 떨어지게 한다
            if j + 1 < n:           # 여기서 줄을 끊는다 → 그 자리의 '품질'을 벌점에 반영
                if SUB_BREAK_STRONG.search(words[j]) or words[j].rstrip(",") in SUB_CONJ:
                    pen *= 0.1      # 절 경계 — 짧아지더라도 여기서 끊는 게 가장 잘 읽힌다
                elif SUB_BREAK_OK.search(words[j]):
                    pen *= 0.4      # 구 경계
                elif _is_adnom(words[j]):
                    pen = pen * 1.4 + max_chars * max_chars * 0.15   # 관형절 — 끊어도 읽힌다
                else:
                    # 조사도 어미도 없이 끝났다 = 뒷말을 꾸미는 말. 가르면 수식어가 홀로
                    # 떨어진다 ("은박 / 봉지가", "군용 / 포장을", "삼분 / 카레고").
                    # 배수로는 못 막는다 — 마지막 줄 앞은 slack 벌점이 0이라 배수가 무의미해서
                    # "그게 오뚜기 삼분 / 카레고" 가 나왔다. 그래서 고정 벌점을 얹는다.
                    pen = pen * 2.0 + max_chars * max_chars * 0.7
            # 실제 낭독의 쉼 — 사람이 숨을 고른 자리가 가장 확실한 의미 경계다.
            # 문법 규칙이 못 잡는 자리도 여기서는 드러난다 (2026-08-11 사용자 제안).
            if gaps and pen:
                g = gaps[j]
                if g >= 0.18:
                    pen *= 0.15     # 여기서 실제로 쉬었다
                elif g >= 0.09:
                    pen *= 0.5
                elif g <= 0.02:
                    pen *= 2.0      # 붙여 읽었다 — 가르면 호흡이 어긋난다
            pen += cross * max_chars * max_chars   # 절을 가로지른 만큼 벌점
            if cost[j + 1] + pen < cost[i]:
                cost[i] = cost[j + 1] + pen
                nxt[i] = j + 1
    out, i = [], 0
    while i < n:
        j = nxt[i]
        out.append(" ".join(words[i:j]))
        i = j
    return out


def sub_chunks(text, max_chars, gaps=None):
    """한 문장을 어절 단위로 묶어 max_chars 이내 조각들로.

    ① 종결부호(. ? ! …) 뒤에서는 **길이와 무관하게** 끊는다 — words_to_cues 와 같은 규칙이다.
       (예전엔 'max_chars 의 절반을 넘을 때만' 이라 짧은 문장이 다음 문장을 끌어와
        "실어버린 거. 비결은 성분이" 가 됐다 — 2026-08-11 제보)
    ② 그렇게 나눈 문장 안에서는 줄 길이가 고르게 되도록 나눈다 (_wrap_balanced).
    ③ 의존명사·단위로 시작하는 어절은 앞말에 붙인다 ("만든 / 게" 방지).

    gaps 는 어절 뒤의 실제 쉼(초). 음성에서 만든 자막이면 넘겨준다 — 사람이 숨을 고른
    자리가 문법 규칙보다 확실한 의미 경계라서, 있으면 그쪽을 우선한다.
    """
    text = (text or "").strip()
    words = [w for w in re.split(r"\s+", text) if w]
    if not words:
        return [text] if text else []
    if gaps and len(gaps) != len(words):
        gaps = None                   # 어절 수가 안 맞으면 신뢰할 수 없다
    # ③ 붙어야 할 어절은 먼저 합쳐 하나의 덩어리로 만든다 — 그래야 ② 가 갈라놓지 못한다.
    #    두 방향이 있다: 의존명사·단위는 **앞말**에(SUB_GLUE), 부정어·관형어는 **뒷말**에(SUB_LEAD).
    #    덩어리의 쉼은 **마지막 어절의 쉼**이다 — 덩어리 끝에서 끊을지를 그 값으로 판단한다.
    glued, gl_gap, pend, pend_g = [], [], "", 0.0
    for i, w in enumerate(words):
        g = gaps[i] if gaps else 0.0
        if pend:                      # 앞 어절이 '안·한·그' 류였다 → 이 어절과 한 덩어리로
            w, pend, pend_g = pend + " " + w, "", 0.0
        elif w in SUB_LEAD:           # 정확히 그 한 글자일 때만 (‘한번’ 같은 낱말은 건드리지 않는다)
            pend, pend_g = w, g
            continue
        if glued and is_sub_glue(w):
            glued[-1] += " " + w
            gl_gap[-1] = g
        else:
            glued.append(w)
            gl_gap.append(g)
    if pend:                          # 문장이 그 어절로 끝나면 앞 덩어리에 붙인다
        if glued:
            glued[-1] += " " + pend
            gl_gap[-1] = pend_g
        else:
            glued.append(pend)
            gl_gap.append(pend_g)
    # ① 문장 경계로 먼저 자른다. 쉼표는 문장이 아니므로 여기서 끊지 않는다
    #    (쉼표까지 끊으면 "그런데, / 사실은" 처럼 두 글자짜리 줄이 쏟아진다)
    sents, cur, cur_g = [], [], []
    for w, g in zip(glued, gl_gap):
        cur.append(w)
        cur_g.append(g)
        if w.endswith((".", "?", "!", "…")):
            sents.append((cur, cur_g))
            cur, cur_g = [], []
    if cur:
        sents.append((cur, cur_g))
    chunks = []
    for s, sg in sents:
        chunks += _wrap_balanced(s, max_chars, sg if gaps else None)
    return chunks or [text]


def sub_resplit(blocks, max_chars=10, min_dur=0.7, max_dur=3.0):
    """SRT 블록들을 화면폭에 맞게 재분할. 구간 시간은 글자 수 비례 + 문장부호 가중치로 배분."""
    out = []
    for b in blocks:
        span = max(0.05, float(b["end"]) - float(b["start"]))
        parts = sub_chunks(b["text"], max_chars)
        eol = bool(b.get("eol"))     # 대본 줄의 끝 — 쪼개도 마지막 조각이 물려받는다
        if len(parts) == 1:
            out.append({"start": b["start"], "end": b["end"], "text": parts[0], "eol": eol})
            continue
        # 가중치 = 공백 제외 글자수 + 문장부호 여유 (쉼표·마침표에서 실제로 쉰다)
        ws = []
        for p in parts:
            w = len(re.sub(r"\s", "", p))
            for ch, add in SUB_PUNCT_W.items():
                if ch in p:
                    w += add * 10
            ws.append(max(w, 1))
        tot = sum(ws)
        t = float(b["start"])
        for i, (p, w) in enumerate(zip(parts, ws)):
            d = span * (w / tot)
            out.append({"start": t, "end": t + d, "text": p,
                        "eol": eol and i == len(parts) - 1})
            t += d
    # 너무 짧은 조각은 병합해 읽을 시간을 확보한다. 단 **문장 경계는 넘지 않는다** —
    # 앞줄이 마침표로 끝났는데 다음 문장 첫 어절을 붙이면
    # "완벽한 균형이었습니다. 세워서" 처럼 두 문장이 한 자막에 섞인다 (2026-08-10 제보).
    # 그런 조각은 앞이 아니라 **뒤 조각과 합친다**.
    def _ends_sentence(c):
        # 부호가 있으면 그걸로, 없으면 대본 줄 끝 표시로 판단한다. 음슴체 대본("~거", "~고")은
        # 마침표를 안 쓰므로 부호만 보면 문장 경계를 하나도 못 찾는다 (2026-08-11 제보).
        return bool(c.get("eol")) or c["text"].rstrip().endswith((".", "?", "!", "…"))

    merged = []
    for idx, c in enumerate(out):
        short = (c["end"] - c["start"]) < min_dur
        prev = merged[-1] if merged else None
        can_back = (prev is not None and short and not _ends_sentence(prev)
                    and len(prev["text"]) + len(c["text"]) + 1 <= max_chars + 4)
        if can_back:
            prev["text"] = (prev["text"] + " " + c["text"]).strip()
            prev["end"] = c["end"]
            prev["eol"] = bool(c.get("eol"))   # 줄 끝을 삼켰으면 이 조각이 줄 끝이 된다
            continue
        # 앞으로 못 붙이면 뒤와 합칠 수 있는지 본다 (문장 첫 어절이 혼자 떨어진 경우)
        nxt = out[idx + 1] if idx + 1 < len(out) else None
        if (short and nxt and not _ends_sentence(c)
                and len(c["text"]) + len(nxt["text"]) + 1 <= max_chars + 4):
            nxt["start"] = c["start"]
            nxt["text"] = (c["text"] + " " + nxt["text"]).strip()
            continue
        merged.append(dict(c))
    for i, c in enumerate(merged, 1):
        c["i"] = i
        c["dur"] = round(c["end"] - c["start"], 2)
        c["len"] = len(re.sub(r"\s", "", c["text"]))
        c["over"] = c["dur"] > max_dur or c["len"] > max_chars
    return merged


def fill_gaps(cues, max_gap=SUB_FILL_MAX):
    """자막 사이의 빈 구간을 앞 자막 쪽으로 늘려 메운다.

    각 줄은 '실제로 말한 구간'만 덮으므로 말 사이 쉼에는 자막이 없다 — 캡컷 타임라인에서
    클립이 잘게 끊기고, 재생하면 글자가 깜빡인다 (2026-08-11 제보: 44줄에 빈 구간 23곳·3.34초).
    max_gap 보다 큰 쉼은 그대로 둔다 — 문장이 끝나고 한 박자 쉬는 자리까지 메우면
    이미 끝난 말이 다음 문장 시작 직전까지 남아 어색하다. 0 이면 전부 메운다."""
    for i in range(len(cues) - 1):
        gap = float(cues[i + 1]["start"]) - float(cues[i]["end"])
        if gap > 0.001 and (max_gap <= 0 or gap <= max_gap):
            cues[i]["end"] = cues[i + 1]["start"]
    return cues


def srt_build(blocks):
    return "\n".join(f"{i}\n{srt_time(b['start'])} --> {srt_time(b['end'])}\n{b['text']}\n"
                     for i, b in enumerate(blocks, 1))


NOTICE_TXT = "본 영상의 일부 이미지는 AI로 생성된 것으로 실제 인물·사건과 무관합니다.\n"


def _parse_cuts(t):
    """컷 분해 응답 파싱 — 코드펜스/앞뒤 설명이 붙어도 살려낸다 (PRD 6-2 구현 주의)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (t or "").strip()).strip()
    try:
        v = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        try:
            v = json.loads(m.group(0))
        except Exception:
            return None
    return v if isinstance(v, dict) and isinstance(v.get("cuts"), list) else None


def _parse_obj(t):
    """단일 JSON 객체 파싱 (원본 분석 응답용) — 코드펜스·앞뒤 설명이 붙어도 살려낸다."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (t or "").strip()).strip()
    try:
        v = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        try:
            v = json.loads(m.group(0))
        except Exception:
            return None
    return v if isinstance(v, dict) else None


def project_dir(cfg, title, make=True):
    """영상 한 편이 쓸 폴더 — <저장폴더>/<날짜>_<제목>/.

    예전에는 이미지만 '쇼츠이미지/<날짜_제목>/' 하위로 모이고 음성·자막·다운로드는
    저장 폴더 루트에 그대로 떨어져서, 한 편의 소스가 세 군데로 흩어졌다
    (2026-08-11 제보: 참고 영상·음악까지 같은 자리에 섞였다).
    이제 한 편의 소스가 모두 이 폴더 아래로 들어간다 — 캡컷에서 폴더 하나만
    열면 그 편의 소스가 전부 있다. 종류별 하위 폴더로 나뉜다 (2026-08-12 정리):
      이미지/ (재생성 이전 판은 이미지/v1, v2…) · 영상/ (+v1…, _미리보기/) · 자막/ (음성+SRT)

    기준 폴더는 img_outdir → typecast_outdir → Downloads 순으로 고른다
    (설정 하나만 채운 사용자도 자연스럽게 한곳으로 모이게)."""
    base = (cfg.get("img_outdir") or "").strip() or \
        (cfg.get("typecast_outdir") or "").strip() or \
        os.path.join(os.path.expanduser("~"), "Downloads", "쇼츠")
    d = os.path.join(base, f"{datetime.now().strftime('%Y%m%d')}_{_safe_name(title or '무제', 30)}")
    if make:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return base
    return d


def tc_format(cfg):
    """타입캐스트에서 받을 오디오 형식 — wav(무손실) | mp3. 아는 값만 통과시킨다."""
    v = str(cfg.get("typecast_format") or "wav").strip().lower()
    return v if v in ("wav", "mp3") else "wav"


def uniq_base(base):
    """이미 쓰인 이름이면 _ver2, _ver3 … 을 붙여 겹치지 않는 경로를 돌려준다.

    음성은 대화상자 없이 바로 저장되므로 덮어쓰면 되돌릴 수 없다 — 파일명이 '날짜+대본
    30자'뿐이라, 같은 날 목소리·시드를 바꿔가며 뽑으면 앞의 판이 조용히 사라졌다
    (2026-08-11 제보). SRT 는 저장 대화상자가 덮어쓰기를 물어보므로 이 문제가 없다.

    확장자를 가리지 않고 본다 — mp3·wav·조각(_1)·_무음제거 가 같은 이름을 공유하므로
    확장자 하나만 확인하면 wav 로 뽑을 때 mp3 판을 못 보고 지나친다."""
    d, name = os.path.dirname(base), os.path.basename(base)
    try:
        used = set(os.listdir(d or "."))
    except OSError:
        return base

    def taken(b):
        bn = os.path.basename(b)
        return any(f == bn or f.startswith(bn + ".") or f.startswith(bn + "_") for f in used)

    if not taken(base):
        return base
    n = 2
    while taken(f"{base}_ver{n}"):
        n += 1
    return f"{base}_ver{n}"


def _safe_name(s, n=12):
    """윈도우 금지문자 제거 + 길이 제한 (파일명용)."""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", (s or "").strip())
    return (s[:n] or "cut").strip() or "cut"


# 자료 이미지의 영상화 — 대본 컷과 규칙이 정반대다. 컷 영상은 "장면이 크게 변해야" 하지만
# 자료 화면은 **아무 일도 일어나지 않는 것이 정답**이다. 종이가 살아 있다는 느낌만 주면 된다.
# 카메라는 항상 고정 — 위에서 평평하게 내려다본 구도라 시점이 조금만 틀어져도 가짜가 된다.
SOURCE_MOTION = {
    "collage": ("The cut paper pieces stay exactly where they are. A slow draught lifts one torn "
                "corner a millimetre and lets it settle, fine dust drifts across the surface, and "
                "the red string tightens once and stills. Nothing slides, nothing is added."),
    "mapboard": ("The map stays flat and still. The taut red thread quivers once and settles, the "
                 "shadows under the brass pins creep a hair as the light shifts, and the lifted "
                 "corner of the paper breathes. The map itself never moves."),
    "vector": ("The flat shapes hold their exact positions. The single accent element brightens "
               "once, softly, and holds — the only change in the frame. Nothing slides, scales, "
               "rotates or is added, and the flat colours never gain shading or texture."),
    "productshot": ("The object stays perfectly still on its seamless ground. The key light "
                    "travels a few degrees across it so the highlight creeps along one edge and "
                    "the contact shadow lengthens slightly. Nothing else moves."),
    "chalkboard": ("The drawing stays exactly as it is. Fine chalk dust drifts through the raking "
                   "light and settles, and the light creeps a little across the slate. No line is "
                   "drawn, redrawn, erased or added."),
    "xray": ("The radiograph holds still. A faint scan of brightness passes once slowly across "
             "the plate from one side to the other, lifting the densest parts as it goes, then "
             "settles back. The subject itself never moves or changes."),
    # 미니어처는 유일하게 카메라가 조금 움직여야 하는 자료 톤이다 (시차로 스케일을 읽힌다).
    # 장면 자체는 그대로 두고 빛·안개만 움직인다 — 요소 개수가 바뀌면 바로 티가 난다.
    "tabletop": ("The scene itself does not move or change at all — every building, tree and "
                 "figure stays exactly where it is and none are added or removed. Fine haze "
                 "drifts slowly through the deepest shadow and the lit windows glow a little "
                 "brighter, then settle."),
}
SOURCE_MOTION_DEFAULT = ("The frame holds still. Only light and fine dust move across it. "
                         "Nothing slides, grows, or is added.")

SOURCE_VIDEO_TAIL = (
    "\nCamera: completely locked for the whole clip — no zoom, pan, tilt, rotation, dolly, "
    "orbit, tracking or handheld shake. One continuous static shot, flat on, exactly the "
    "framing of the provided image.\n"
    "Keep the provided image's composition, materials, colours and lighting exactly as they are. "
    "Every element stays in its place at its size; nothing enters or leaves the frame.\n"
    "Avoid: adding or changing any text, letters, numbers or marks; redrawing, sharpening or "
    "completing anything that is blurred or blacked out; editing cuts, transitions, morphing or "
    "time skips; people, hands, faces or voices; music.")
# 사용자가 카메라를 직접 고른 경우 — 위 꼬리의 '완전 고정' 문장을 빼야 한다.
# 두 지시가 같이 나가면 정면으로 싸워서 카메라가 어중간하게 떨린다.
# 대신 **내용은 그대로 두라**는 잠금은 유지한다 — 자료 화면은 카메라가 움직이면 새로 드러난
# 영역을 모델이 지어내서 요소 개수가 바뀐다 (실측 2026-08-13: 스키어 5명→2명→7명).
SOURCE_VIDEO_TAIL_FREECAM = (
    "\nThe camera move above is the only movement — smooth, slow and continuous, one single "
    "take, no cuts.\n"
    "Keep the provided image's composition, materials, colours and lighting exactly as they are. "
    "Every element stays in its place at its size; nothing is added, removed, duplicated or "
    "invented as the camera reveals new area.\n"
    "Avoid: adding or changing any text, letters, numbers or marks; redrawing, sharpening or "
    "completing anything that is blurred or blacked out; editing cuts, transitions, morphing or "
    "time skips; people, hands, faces or voices; music.")


# '자유' 전용 꼬리 (2026-08-15) — 워크를 지정하지 않고 잠금만 푸는 상태.
# FREECAM 꼬리를 그대로 쓰면 "위의 카메라 워크가 유일한 움직임"이라는 문장이 가리킬 대상이
# 없어 허공을 가리킨다. 대신 '작고 느린 움직임까지만'으로 상한을 준다 — 완전 방임은
# 자료 화면에서 요소 개수가 바뀌는 실패로 직결된다 (실측 2026-08-13: 스키어 5명→2명→7명).
SOURCE_VIDEO_TAIL_FREE = (
    "\nThe camera may drift gently if it helps the shot — a slow, small, continuous move at most, "
    "one single take, no cuts. It never swings, spins or travels far.\n"
    "Keep the provided image's composition, materials, colours and lighting exactly as they are. "
    "Every element stays in its place at its size; nothing is added, removed, duplicated or "
    "invented as the camera reveals new area.\n"
    "Avoid: adding or changing any text, letters, numbers or marks; redrawing, sharpening or "
    "completing anything that is blurred or blacked out; editing cuts, transitions, morphing or "
    "time skips; people, hands, faces or voices; music.")


def source_video_prompt(style, cam="", free=False):
    """자료 이미지 한 장을 영상으로 만들 때 쓰는 프롬프트.

    cam 을 주면 그 카메라 워크 문구를 앞에 붙이고, 꼬리의 '카메라 고정' 지시를 뺀다 —
    두 지시가 같이 나가면 정면으로 싸운다. 안 주면 예전과 똑같이 고정 문구가 붙는다.
    free=True 는 '워크는 지정 안 하되 잠금만 푼다' — 머리 문구 없이 꼬리만 바꾼다."""
    tail = SOURCE_VIDEO_TAIL
    head = ""
    if cam in CAMERA_PRESETS:
        head = f"Camera: {CAMERA_PRESETS[cam]}\n"
        tail = SOURCE_VIDEO_TAIL_FREECAM
    elif free:
        tail = SOURCE_VIDEO_TAIL_FREE
    return (head + "Animate the provided image.\nMotion: "
            + SOURCE_MOTION.get(norm_style(style), SOURCE_MOTION_DEFAULT) + tail)


def source_outdir(cfg, make=True):
    """자료 이미지 저장 폴더. 편(project_dir)과 달리 **날짜 하나로 모은다** —
    본편에 딸린 소스가 아니라 여러 편에 두루 쓰는 재료라, 편별로 흩어 놓으면 다시 못 찾는다."""
    base = (cfg.get("img_outdir") or "").strip() or \
        (cfg.get("typecast_outdir") or "").strip() or \
        os.path.join(os.path.expanduser("~"), "Downloads", "쇼츠")
    d = os.path.join(base, "자료이미지", datetime.now().strftime("%Y%m%d"))
    if make:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return base
    return d


# ── 영상 판 관리 — 파일을 옮기지 않고 이름으로 쌓는다 (2026-08-19, PRD: 원본 고정) ──
# 캡컷은 소재를 경로+파일명으로 문다. 예전처럼 재생성이 같은 이름 자리를 갈아치우면
# **편집 중인 타임라인의 그림이 조용히 바뀐다**. 그래서 영상은 절대 덮지도 옮기지도 않고
# `NN_장면_v1.mp4 / _v2 / _v3` 로 나란히 쌓는다. 앱은 최신 판을 보여주되 파일은 불변.
_VER_RE = re.compile(r"_v(\d+)$", re.I)


def vid_versions(outdir, no):
    """컷 번호의 모든 판 — [(판번호, 경로)] 을 판번호 오름차순으로.

    ⚠ 정렬은 **정수**로 한다 — 문자열이면 _v10 이 _v2 앞에 온다.
    ⚠ 묶는 기준은 **컷 번호**다 — 재생성 사이에 장면 요약을 고치면 파일명이 달라지므로
      이름으로 묶으면 같은 컷의 판이 흩어진다.
    ⚠ 번호 없는 파일(구규칙 `01_장면.mp4`)은 v0(레거시)로 본다 — 옛 편과 섞여도 안전하게."""
    out = []
    try:
        for fn in os.listdir(outdir):
            if not fn.startswith(f"{int(no):02d}_") or not fn.lower().endswith(".mp4"):
                continue
            if not os.path.isfile(os.path.join(outdir, fn)):
                continue
            stem = os.path.splitext(fn)[0]
            m = _VER_RE.search(stem)
            out.append((int(m.group(1)) if m else 0, os.path.join(outdir, fn)))
    except Exception:
        return []
    return sorted(out, key=lambda x: x[0])


def vid_latest(outdir, no):
    """그 컷의 최신 판 경로 (없으면 "")."""
    v = vid_versions(outdir, no)
    return v[-1][1] if v else ""


def vid_next_path(outdir, no, scene_name):
    """다음 판을 저장할 경로. 폴더의 실제 파일을 보고 비어 있는 다음 번호를 고른다 —
    앱을 껐다 켜도, 다른 세션이 끼어들어도 이어서 쌓인다."""
    used = {v for v, _ in vid_versions(outdir, no)}
    n = 1
    while n in used:
        n += 1
    return os.path.join(outdir, f"{int(no):02d}_{scene_name}_v{n}.mp4")


def _archive_one(path, exts=(".mp4", ".webm")):
    """**파일 하나**(와 같은 이름의 미리보기)를 v1/·v2/ 로 옮겨 보관한다.

    _archive_prev 는 컷 번호 접두어("01_…")로 찾지만 자료 소스는 파일명 규칙이 달라
    한 건도 못 잡는다 → 경로를 직접 받는다. 덮어쓰면 마음에 들던 판이 사라지는 건
    컷 영상이든 자료 영상이든 똑같다."""
    d = os.path.dirname(path)
    name = os.path.splitext(os.path.basename(path))[0]
    moved = []
    for ext in exts:
        src = os.path.join(d, name + ext)
        if not os.path.exists(src):
            continue
        v = 1
        while os.path.exists(os.path.join(d, f"v{v}", name + ext)):
            v += 1
        try:
            vd = os.path.join(d, f"v{v}")
            os.makedirs(vd, exist_ok=True)
            dst = os.path.join(vd, name + ext)
            os.replace(src, dst)
            moved.append((src, dst))
        except Exception:
            pass
    return moved


def _archive_prev(outdir, no, exts=(".png", ".jpg", ".webp")):
    """재생성 전에 같은 컷 번호의 기존 파일을 v1/, v2/… 버전 폴더로 옮긴다.
    덮어쓰면 마음에 들던 이전 결과가 사라져서 비교·복구가 불가능해진다.
    (예전엔 _이전/ 하위에 _v1 접미사로 쌓았다 — 2026-08-12 버전 폴더 방식 전환.
     v1 이 가장 오래된 판, 번호가 클수록 최근에 밀린 판이다.)
    현재 폴더에는 항상 최신본만 깔끔한 이름으로 남아 체인·시작프레임·편집 임포트가 그걸 집는다."""
    try:
        names = [f for f in os.listdir(outdir)
                 if f.startswith(f"{no:02d}_") and f.lower().endswith(exts)
                 and os.path.isfile(os.path.join(outdir, f))]
    except Exception:
        return []
    moved = []   # [(원경로, 이동경로)] — 재생성 실패 시 원위치 복원용
    for fn in names:
        v = 1   # 같은 이름이 이미 있는 버전 폴더는 건너뛰고 빈 자리에 넣는다
        while os.path.exists(os.path.join(outdir, f"v{v}", fn)):
            v += 1
        vdir = os.path.join(outdir, f"v{v}")
        try:
            os.makedirs(vdir, exist_ok=True)
            src, dstp = os.path.join(outdir, fn), os.path.join(vdir, fn)
            os.replace(src, dstp)
            moved.append((src, dstp))
        except Exception:
            pass
    return moved


def _img_ext(raw, mime=None):
    """실제 바이트(매직넘버) 우선으로 확장자를 정한다.
    Gemini 이미지 응답은 모델에 따라 PNG가 아니라 JPEG로 온다(2026-08-03 실측 lite=JPEG).
    확장자와 내용이 다르면 편집 프로그램에서 임포트가 깨지므로 반드시 맞춰서 저장한다."""
    if raw[:4] == b"\x89PNG": return ".png"
    if raw[:3] == b"\xff\xd8\xff": return ".jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP": return ".webp"
    return {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg",
            "image/webp": ".webp"}.get((mime or "").lower(), ".png")


class Api:
    def __init__(self):
        self._emit = None  # 메인스레드로 JS 실행을 넘기는 콜백 (Bridge.runJs.emit)
        self.running = False
        self.img_running = False  # 이미지 생성 중단 플래그
        self.vid_running = False  # 영상 생성 중단 플래그
        self._gen_lock = threading.Lock()  # 검사→플래그 설정을 원자화 (더블클릭 이중 배치 방지)

    def _js(self, fn, arg):
        """프론트로 밀어 올리기. **여기서 실패하면 화면이 영원히 '처리중' 으로 멈춘다** —
        결과를 기다리는 쪽은 이 콜백 하나뿐이기 때문이다. 그래서 조용히 넘기지 않는다
        (2026-08-16: except: pass 때문에 컷 붙여넣기가 왜 멈추는지 알 수가 없었다)."""
        if not self._emit:
            return
        try:
            payload = json.dumps(arg, ensure_ascii=False)
        except Exception as e:
            # 직렬화 실패 — 최소한 '실패했다'는 사실은 반드시 올려보낸다
            payload = json.dumps({"ok": False, "error": f"결과를 보내지 못했습니다 (직렬화 {e})"},
                                 ensure_ascii=False)
        try:
            # U+2028/2029 는 JSON 에선 유효하지만 JS 소스에선 줄바꿈으로 취급돼 구문이 깨진다
            payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            self._emit(f"window.{fn} && window.{fn}({payload})")
        except Exception as e:
            self._last_emit_err = f"{fn}: {e}"
            try:
                self._emit("window.__pushErr && window.__pushErr(%s)"
                           % json.dumps(f"{fn} 전달 실패: {e}", ensure_ascii=False))
            except Exception:
                pass

    def get_config(self):
        return load_config()

    def save_config(self, data):
        # _CFG_LOCK: 생성 배치의 사용량 기록(load→수정→save)과 겹치면 나중 쓰기가 앞 쓰기를
        # 통째로 덮어써서, 방금 저장한 API 키가 조용히 증발했다 (2026-08-11 실사고: anthropic_key)
        with _CFG_LOCK:
            cfg = load_config(); cfg.update(data); save_config(cfg)
        return {"ok": True}

    # ────────────── 대본 스튜디오 (Claude API) ──────────────
    # 프리셋(제작파일/<폴더>) 하나 = 지침 md + 레퍼런스 + 대본 + 제작이력.
    # 지침·레퍼런스를 프리픽스로 캐싱해 주제 추천 / 대본을 뽑는다.
    # 느린 호출은 스레드로 돌리고 진행 상황은 _js로 밀어 올린다.

    def lm_presets(self):
        '''탭 진입 시 1회 — 프리셋 목록과 모델 목록.'''
        try:
            import studio
            return {"ok": True, "presets": studio.list_presets(), "models": studio.MODELS}
        except ImportError:
            return {"ok": False, "error": "anthropic 패키지가 없습니다.  pip install anthropic"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    def lm_kit(self, params):
        '''프리셋 전환 시 — 지침·레퍼런스·폼 항목·이력.'''
        try:
            import studio
            pid = params.get("preset", "")
            k = studio.load_kit(pid)
            return {"ok": True, "preset": pid, "label": k["conf"]["label"], "tone": k["conf"]["tone"],
                    "guide": k["guide_file"], "refs": k["ref_files"], "chars": k["chars"],
                    "fields": k["conf"]["fields"], "history": studio.history_load(pid)[-30:]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    def _lm_claim(self, kind):
        '''중복 실행 차단. 버튼 비활성화만으로는 못 막는 경우(더블클릭·재진입)를 서버에서 잠근다.
        API 호출은 건당 과금이라 이중 호출 = 이중 청구다.'''
        with self._gen_lock:
            if getattr(self, "_lm_busy", None):
                return False
            self._lm_busy = kind
            return True

    def _lm_release(self):
        with self._gen_lock:
            self._lm_busy = None

    def lm_search_titles(self, params=None):
        """유튜브에서 실제로 나온 영상 제목을 긁어 '이미 다뤄진 각도' 목록으로 만든다.

        §0-b의 "이 각도로 이미 나온 영상이 있는가" 자문을 추측이 아니라 근거로 바꾼다.
        쿼터: search.list 100 + videos.list 1 = 101 units/회.
        """
        p = params or {}
        q = (p.get("q") or "").strip()
        if not q:
            return {"ok": False, "error": "검색어를 입력하세요."}
        cfg = load_config()
        key = (cfg.get("youtube_api_key") or "").strip()
        if not key:
            return {"ok": False, "error": "설정에 YouTube Data API 키가 필요합니다."}
        n = max(5, min(30, int(_num(p.get("n"), 20))))
        try:
            yt = build("youtube", "v3", developerKey=key)
            sr = yt.search().list(part="id", q=q, type="video", maxResults=n,
                                  order=(p.get("order") or "relevance"),
                                  regionCode="KR", relevanceLanguage="ko").execute()
            ids = [it["id"]["videoId"] for it in sr.get("items", []) if it.get("id", {}).get("videoId")]
            if not ids:
                return {"ok": False, "error": f"'{q}' 검색 결과가 없습니다."}
            rows = _yt_build_rows(yt, ids)
            rows = sorted(rows.values() if isinstance(rows, dict) else rows,
                          key=lambda r: -int(r.get("views") or 0))
        except Exception as e:
            return {"ok": False, "error": f"검색 실패: {str(e)[:180]}"}
        out, lines = [], []
        for r in rows:
            v = int(r.get("views") or 0)
            x = float(r.get("outlier") or 0)   # 채널 평균 대비 배수 — 조회수 절대값보다 신호가 세다
            vs = f"{v/10000:.0f}만" if v >= 10000 else f"{v:,}"
            tag = f"(조회수 {vs} · 채널 평균의 {x}배)" if x > 0 else f"(조회수 {vs})"
            out.append({"title": r.get("title", ""), "views": v, "outlier": x,
                        "channel": r.get("channel", ""), "dur": r.get("dur", 0)})
            lines.append(f"{r.get('title','')}  {tag}")
        return {"ok": True, "rows": out, "text": "\n".join(lines), "units": 102, "q": q}

    def lm_topics_run(self, params):
        if not self._lm_claim("topics"):
            return {"ok": False, "error": "이미 실행 중입니다. 끝난 뒤에 다시 눌러주세요."}
        threading.Thread(target=self._lm_topics, args=(params,), daemon=True).start()
        return {"ok": True}

    def _lm_topics(self, params):
        try:
            import studio
            cfg = load_config()
            self._js("lmStatus", "주제 후보 뽑는 중… (지침·레퍼런스 로드 + 판정 채점)")
            r = studio.recommend_topics(
                cfg.get("anthropic_key", ""), params.get("preset", ""),
                model=params.get("model") or cfg.get("lm_model_topic") or studio.DEFAULT_MODEL,
                count=int(params.get("count") or 5), hint=params.get("hint", ""),
                ref_titles=params.get("ref_titles", ""),
                effort=params.get("effort") or "medium")
            self._js("lmTopics", r)
        except Exception as e:
            self._js("lmTopics", {"ok": False, "error": str(e)[:300]})
        finally:
            self._lm_release()

    def lm_script_run(self, params):
        if not self._lm_claim("script"):
            return {"ok": False, "error": "이미 실행 중입니다. 끝난 뒤에 다시 눌러주세요."}
        threading.Thread(target=self._lm_script, args=(params,), daemon=True).start()
        return {"ok": True}

    def _lm_script(self, params):
        try:
            import studio
            cfg = load_config()
            topic = (params.get("topic") or "").strip()
            if not topic:
                self._js("lmScript", {"ok": False, "error": "소재를 입력하세요."}); return
            self._js("lmStatus", f"'{topic}' 대본 쓰는 중… (Opus는 1~3분 걸릴 수 있습니다)")
            r = studio.write_script(
                cfg.get("anthropic_key", ""), params.get("preset", ""), topic,
                fields=params.get("fields") or {},
                model=params.get("model") or cfg.get("lm_model_script") or studio.DEFAULT_MODEL,
                note=params.get("note", ""), effort=params.get("effort") or "high")
            r["topic"] = topic
            r["fields"] = params.get("fields") or {}
            self._js("lmScript", r)
        except Exception as e:
            self._js("lmScript", {"ok": False, "error": str(e)[:300]})
        finally:
            self._lm_release()

    def lm_revise_run(self, params):
        '''마음에 안 드는 부분만 고친다. 전체 재생성보다 싸고 빠르며 좋았던 문장이 안 날아간다.'''
        if not self._lm_claim("revise"):
            return {"ok": False, "error": "이미 실행 중입니다. 끝난 뒤에 다시 눌러주세요."}
        threading.Thread(target=self._lm_revise, args=(params,), daemon=True).start()
        return {"ok": True}

    def _lm_revise(self, params):
        try:
            import studio
            cfg = load_config()
            self._js("lmStatus", "지적한 부분만 고치는 중… (나머지 문장은 그대로 둡니다)")
            r = studio.revise_script(
                cfg.get("anthropic_key", ""), params.get("preset", ""),
                params.get("current", ""), params.get("request", ""),
                model=params.get("model") or cfg.get("lm_model_script") or studio.DEFAULT_MODEL,
                effort=params.get("effort") or "high")
            r["topic"] = params.get("topic", "")
            r["fields"] = params.get("fields") or {}
            self._js("lmScript", r)
        except Exception as e:
            self._js("lmScript", {"ok": False, "error": str(e)[:300]})
        finally:
            self._lm_release()

    def lm_save(self, params):
        '''채택한 대본을 파일로 저장하고 제작이력에 기록 (다음 추천의 중복 제외 근거).'''
        try:
            import studio
            pid = params.get("preset", "")
            path = studio.save_script(pid, params.get("topic", ""), params.get("text", ""),
                                      fields=params.get("fields") or {})
            return {"ok": True, "path": path, "history": studio.history_load(pid)[-30:]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    def lm_analyze(self, params):
        '''대본 텍스트를 프리셋 규칙과 대조. API 호출 없음 = 무료.'''
        try:
            import studio
            return {"ok": True, "stats": studio.analyze(params.get("text", ""), params.get("preset") or None)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    def lm_open_folder(self, params):
        try:
            import studio
            os.startfile(studio.out_dir(params.get("preset", "")))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def open_url(self, url):
        # QtWebEngine은 외부 링크/새창을 기본 차단 → 시스템 기본 브라우저로 연다
        try:
            import webbrowser
            webbrowser.open(str(url))
        except Exception:
            pass
        return {"ok": True}

    def stop_community(self):
        self.running = False
        return {"ok": True}

    def start_community(self, params):
        threading.Thread(target=self._crawl, args=(params,), daemon=True).start()
        return {"ok": True}

    def _crawl(self, params):
        cfg = load_config()
        self.running = True
        sites = params.get("sites") or ["더쿠"]
        sp, ep = int(params.get("sp", 1)), int(params.get("ep", 5))
        use_proxy = params.get("proxy", True)
        rows = []
        for site in sites:
            if not self.running: break
            base, parser = SITES[site]
            self._js("addLog", f"▶ {site} {sp}~{ep}p 시작")
            prev = base
            for page in range(sp, ep + 1):
                if not self.running: break
                sep = "&" if "?" in base else "?"
                url = base if page == 1 else f"{base}{sep}page={page}"
                got = None
                for attempt in range(1, 4):
                    try:
                        if "theqoo.net" in base and attempt >= 2:
                            html = unlocker(cfg, url)
                        else:
                            r = scraper.get(url, headers=rand_headers(prev),
                                            proxies=make_proxy(cfg) if use_proxy else None, timeout=15, verify=False)
                            html = r.text
                        got = parser(html, site)
                        if got: break
                    except Exception as e:
                        self._js("addLog", f"  ⚠ {site} {page}p 시도{attempt}: {str(e)[:60]}")
                        time.sleep(random.uniform(2, 4))
                if got:
                    rows.extend(got)
                    self._js("addLog", f"  ✓ {site} {page}p — {len(got)}개")
                    prev = url
                    time.sleep(random.uniform(2, 4))
                else:
                    self._js("addLog", f"  ✗ {site} {page}p 실패")
        self._js("addLog", f"✅ 완료 — 총 {len(rows)}개")
        self._js("renderCommunity", rows)
        self.running = False

    # ── 유튜브 ──
    def youtube_search(self, params):
        # GUI 안 막게 스레드에서 수행 → 결과는 renderYt로 푸시
        threading.Thread(target=self._search, args=(params,), daemon=True).start()
        return {"ok": True}

    def _search(self, params):
        cfg = load_config()
        if not cfg.get("youtube_api_key"):
            self._js("renderYt", {"ok": False, "error": "설정에 YouTube API 키가 없습니다."}); return
        try:
            if params.get("mode") == "favorites":
                chans = cfg.get("yt_fav_channels", [])
                if not chans:
                    self._js("renderYt", {"ok": False, "error": "관심채널이 없습니다. ➕ 추가로 채널을 등록하세요."}); return
                rows = yt_collect_favorites(cfg["youtube_api_key"], chans,
                                            params.get("period", "7"), params.get("length", "전체"))
            else:
                rows = yt_collect(cfg["youtube_api_key"], params.get("mode", "keyword"),
                                  params.get("query", ""), int(params.get("max", 60)),
                                  params.get("region", "한국"), params.get("period", "30"),
                                  params.get("length", "전체"))
            self._js("renderYt", {"ok": True, "rows": rows})
        except Exception as e:
            self._js("renderYt", {"ok": False, "error": str(e)[:200]})

    # ── 관심채널 관리 (config.json yt_fav_channels: [{id, name}]) ──
    def yt_fav_add(self, params):
        # 채널 resolve에 네트워크가 필요 → 스레드에서 수행 후 renderFavs 푸시
        threading.Thread(target=self._fav_add, args=(params,), daemon=True).start()
        return {"ok": True}

    def _fav_add(self, params):
        cfg = load_config()
        raw = (params or {}).get("query", "").strip()
        if not raw:
            self._js("renderFavs", {"ok": False, "error": "채널명·@핸들·URL을 입력하세요"}); return
        if not cfg.get("youtube_api_key"):
            self._js("renderFavs", {"ok": False, "error": "설정에 YouTube API 키가 없습니다."}); return
        try:
            yt = build("youtube", "v3", developerKey=cfg["youtube_api_key"])
            cid = resolve_channel_id(yt, raw)
            if not cid:
                self._js("renderFavs", {"ok": False, "error": f"채널을 찾을 수 없습니다: {raw}"}); return
            favs = cfg.get("yt_fav_channels", [])
            if any(c.get("id") == cid for c in favs):
                self._js("renderFavs", {"ok": True, "channels": favs}); return
            name = raw
            try:
                r = yt.channels().list(part="snippet", id=cid).execute()
                if r.get("items"):
                    name = r["items"][0]["snippet"]["title"]
            except Exception:
                pass
            favs.append({"id": cid, "name": name})
            cfg["yt_fav_channels"] = favs
            save_config(cfg)
            self._js("renderFavs", {"ok": True, "channels": favs})
        except Exception as e:
            self._js("renderFavs", {"ok": False, "error": str(e)[:200]})

    def yt_fav_remove(self, params):
        cfg = load_config()
        favs = [c for c in cfg.get("yt_fav_channels", []) if c.get("id") != (params or {}).get("id")]
        cfg["yt_fav_channels"] = favs
        save_config(cfg)
        return {"ok": True, "channels": favs}

    def youtube_subs(self, params):
        threading.Thread(target=self._subs, args=(params.get("videos", []),), daemon=True).start()
        return {"ok": True}

    def _subs(self, vids):
        blocks, results, failed, ok, fail = [], [], [], 0, 0
        for i, v in enumerate(vids):
            self._js("ytStatus", f"자막 추출 {i + 1}/{len(vids)} — {v['title'][:28]}…")
            link = f"https://www.youtube.com/watch?v={v['videoId']}"
            txt = yt_transcript(v["videoId"])
            if txt:
                body = merge_lines(txt.split("\n"))
                blocks.append(f"[제목] {v['title']}\n[링크] {link}\n\n{body}\n\n{'=' * 50}\n")
                results.append({"title": v["title"], "link": link, "text": body})
                ok += 1
            else:
                fail += 1
                failed.append({"title": v["title"], "link": link})
            # 유튜브 timedtext는 연속 호출에 429를 뱉는다. 1초는 너무 짧아 뒤쪽 영상이 통째로 날아갔다.
            if i < len(vids) - 1:
                time.sleep(2.5)
        path = ""
        if blocks:
            path = os.path.join(BASE_DIR, f"youtube_자막_{datetime.now():%Y%m%d_%H%M%S}.txt")
            open(path, "w", encoding="utf-8").write("\n".join(blocks))
        self._js("renderSubs", {"results": results, "ok": ok, "fail": fail,
                                "failed": failed, "file": os.path.basename(path)})

    # ── 원본 추적 (프레임 역검색) ──
    # 역검색용 공개 업로드: catbox.moe는 국내 ISP 차단 사례가 많아 여러 호스트를 순차 시도.
    # 성공한 호스트를 기억해 다음 프레임은 그 호스트부터 (프레임당 대기 최소화)
    _upload_pref = 0

    @staticmethod
    def _up_catbox(fp, ua):
        with open(fp, "rb") as f:
            r = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"},
                              files={"fileToUpload": f}, headers=ua, timeout=20)
        t = r.text.strip()
        return t if (r.status_code == 200 and t.startswith("http")) else ""

    @staticmethod
    def _up_0x0(fp, ua):
        with open(fp, "rb") as f:
            r = requests.post("https://0x0.st", files={"file": f}, headers=ua, timeout=20)
        t = r.text.strip()
        return t if (r.status_code == 200 and t.startswith("http")) else ""

    @staticmethod
    def _up_tmpfiles(fp, ua):
        with open(fp, "rb") as f:
            r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}, headers=ua, timeout=20)
        u = ((r.json().get("data") or {}).get("url", "")) if r.status_code == 200 else ""
        # 페이지 URL → 직접 이미지 URL (역검색 엔진이 서버에서 가져가야 하므로)
        return u.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1) if u.startswith("http") else ""

    @staticmethod
    def _up_uguu(fp, ua):
        with open(fp, "rb") as f:
            r = requests.post("https://uguu.se/upload.php?output=text", files={"files[]": f}, headers=ua, timeout=20)
        t = r.text.strip()
        return t if (r.status_code == 200 and t.startswith("http")) else ""

    def _upload_public(self, fp):
        ua = {"User-Agent": UA_POOL[0]}
        # uguu 1순위: 국내 회선 실측에서 catbox(차단)·0x0·tmpfiles 실패, uguu만 성공 (2026-07-14)
        hosts = [self._up_uguu, self._up_catbox, self._up_0x0, self._up_tmpfiles]
        order = list(range(len(hosts)))
        order.remove(self._upload_pref); order.insert(0, self._upload_pref)
        for i in order:
            try:
                u = hosts[i](fp, ua)
                if u:
                    Api._upload_pref = i
                    return u
            except Exception:
                pass
        return ""

    def source_trace(self, params):
        threading.Thread(target=self._source_trace, args=(params,), daemon=True).start()
        return {"ok": True}

    def _source_trace(self, params):
        import cv2, tempfile
        url = normalize_media_url((params or {}).get("url", ""))
        if not url:
            self._js("renderTrace", {"ok": False, "error": "영상 URL을 입력하세요."}); return
        count = int((params or {}).get("count", 6))
        tmp = tempfile.mkdtemp(prefix="trace_")
        vp = os.path.join(tmp, "v.mp4")
        self._js("traceStatus", "영상 다운로드 중…")
        is_insta = bool(re.search(r"instagram\.com/(?:[\w.]+/)?(?:p|reels?|tv)/", url))
        cfg = load_config()
        if is_insta and cfg.get("apify_token"):
            # 인스타는 비로그인 yt-dlp가 차단됨('empty media response') → Apify로 mp4 직접 획득
            self._js("traceStatus", "인스타 영상 주소 조회 중… (Apify)")
            try:
                mp4 = apify_post_video(cfg["apify_token"], url)
                self._js("traceStatus", "인스타 영상 다운로드 중…")
                buf = requests.get(mp4, timeout=60).content
                open(vp, "wb").write(buf)
            except Exception as e:
                self._js("renderTrace", {"ok": False, "error": f"인스타 다운로드 실패: {str(e)[:150]}"}); return
        else:
            try:
                opts = {"format": "18/best[ext=mp4][height<=480]/worst", "outtmpl": vp,
                        "quiet": True, "no_warnings": True, "noprogress": True,
                        "extractor_args": {"youtube": {"player_client": ["web_safari", "android", "ios"]}}}
                with yt_dlp.YoutubeDL(opts) as y:
                    y.download([url])
            except Exception as e:
                msg = f"다운로드 실패: {str(e)[:120]}"
                if is_insta:
                    msg += " — 인스타는 설정에 Apify 토큰을 넣으면 우회 다운로드됩니다"
                self._js("renderTrace", {"ok": False, "error": msg}); return
        if not os.path.exists(vp):
            self._js("renderTrace", {"ok": False, "error": "다운로드 실패 (영상 접근 불가)"}); return
        self._js("traceStatus", "키프레임 추출 중…")
        cap = cv2.VideoCapture(vp)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        frames = []
        for i in range(count):
            pos = (i + 1) / (count + 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * pos) if total else 0)
            ok, fr = cap.read()
            if ok:
                fp = os.path.join(tmp, f"f{i}.jpg")
                cv2.imwrite(fp, fr)
                frames.append(fp)
        cap.release()
        if not frames:
            self._js("renderTrace", {"ok": False, "error": "프레임 추출 실패 (영상 형식 확인)"}); return
        import base64
        out = []
        for i, fp in enumerate(frames):
            self._js("traceStatus", f"프레임 처리 {i + 1}/{len(frames)}… (미리보기+역검색 준비)")
            # 미리보기: 로컬 프레임을 base64로 (원격호스트 안 거치므로 항상 보임)
            try:
                with open(fp, "rb") as f:
                    thumb = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
            except Exception:
                thumb = ""
            # 역검색용 공개 URL (Yandex/Lens가 서버에서 가져감) — 호스트 4곳 순차 시도
            img = self._upload_public(fp)
            out.append({"thumb": thumb, "img": img,
                        "yandex": ("https://yandex.com/images/search?rpt=imageview&url=" + img) if img else "",
                        "lens": ("https://lens.google.com/uploadbyurl?url=" + img) if img else ""})
        out = [o for o in out if o["thumb"] or o["img"]]
        if not out:
            self._js("renderTrace", {"ok": False, "error": "프레임 처리 실패"}); return
        ok_up = sum(1 for o in out if o["img"])
        self._js("renderTrace", {"ok": True, "frames": out})
        if ok_up == 0:
            self._js("traceStatus", f"⚠ 프레임 {len(out)}장 추출됐지만 역검색 업로드가 전부 실패 — 네트워크/방화벽 확인 후 다시 시도")
        else:
            self._js("traceStatus", f"✅ 프레임 {len(out)}장 (역검색 준비 {ok_up}장) — Yandex(강력)/Lens 클릭")

    # ── 다운로더 (유튜브·틱톡·도우인·샤오홍슈·인스타) ──
    def open_file(self, path):
        """파일을 OS 기본 프로그램으로 연다.

        컷 카드의 <video> 는 QtWebEngine 기본 빌드에 H.264/AAC 디코더가 없어 재생되지 않는다
        (이미지는 정상, 영상만 조용히 실패). 생성물이 h264+aac 라 브라우저 안에서는 못 튼다 →
        시스템 플레이어로 넘긴다. (2026-08-10 확인)
        """
        try:
            p = os.path.abspath(str(path or ""))
            if not os.path.exists(p):
                return {"ok": False, "error": "파일을 찾지 못했습니다."}
            os.startfile(p)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}

    def open_folder(self, path):
        try:
            p = path if os.path.isdir(path) else os.path.dirname(path)
            os.startfile(p)
        except Exception:
            pass
        return {"ok": True}

    def download_media(self, params):
        threading.Thread(target=self._download, args=(params,), daemon=True).start()
        return {"ok": True}

    def _dl_external(self, exe, url, quality, outdir, cookie_args=None):
        """'다운로더' 폴더의 yt-dlp.exe로 다운로드 — deno·ffmpeg도 그 폴더 것 사용.
        내장 라이브러리와 달리 yt-dlp.exe -U 로 재빌드 없이 유튜브 차단 대응 가능."""
        import subprocess, tempfile
        tooldir = os.path.dirname(exe)
        args = [exe, "--newline", "--no-warnings",
                "-o", os.path.join(outdir, "%(title).80s [%(id)s].%(ext)s")]
        args += cookie_args or []
        if os.path.exists(os.path.join(tooldir, "ffmpeg.exe")):
            args += ["--ffmpeg-location", tooldir]
        if quality == "audio":
            args += ["-x", "--audio-format", "mp3", "--audio-quality", "192K"]
        else:
            h = {"1080": 1080, "720": 720, "480": 480}.get(quality)
            args += ["-f", f"bestvideo[height<={h}]+bestaudio/best[height<={h}]" if h else "bestvideo+bestaudio/best",
                     "--merge-output-format", "mp4"]
        done = os.path.join(tempfile.gettempdir(), f"ytdlp_out_{os.getpid()}_{threading.get_ident()}.txt")
        args += ["--print-to-file", "after_move:filepath", done, url]
        env = dict(os.environ)
        env["PATH"] = tooldir + os.pathsep + env.get("PATH", "")  # deno.exe (유튜브 검증 우회용) 탐색 경로
        self._js("dlStatus", "다운로드 시작…")
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="ignore",
                                    env=env, creationflags=0x08000000)  # CREATE_NO_WINDOW
            last_err = ""
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("[download]"):
                    m = re.search(r"(\d{1,3}(?:\.\d)?)%", line)
                    if m:
                        self._js("dlStatus", f"다운로드 중… {m.group(1)}%")
                elif line.startswith(("[Merger]", "[ExtractAudio]")):
                    self._js("dlStatus", "병합/변환 중… (잠시)")
                elif "ERROR" in line:
                    last_err = line
            proc.wait()
            path = ""
            try:
                with open(done, encoding="utf-8", errors="ignore") as f:
                    lines = [l.strip() for l in f if l.strip()]
                if lines:
                    path = lines[-1]
            except Exception:
                pass
            try:
                os.remove(done)
            except Exception:
                pass
            if not (path and os.path.exists(path)):
                if quality == "audio" and path:  # 확장자 치환 케이스 방어
                    alt = os.path.splitext(path)[0] + ".mp3"
                    if os.path.exists(alt):
                        path = alt
            if not (path and os.path.exists(path)):
                raise RuntimeError(last_err[:300] or f"yt-dlp 종료 코드 {proc.returncode}")
            self._js("renderDownload", {"ok": True, "file": os.path.basename(path), "path": path, "dir": outdir})
        except Exception as e:
            self._js("renderDownload", {"ok": False, "error": dl_error_hint(url, str(e)[:300])})

    def _download(self, params):
        url = (params or {}).get("url", "").strip()
        quality = (params or {}).get("quality", "best")
        if not url:
            self._js("renderDownload", {"ok": False, "error": "영상 URL을 입력하세요."}); return
        fixed = normalize_media_url(url)
        if fixed != url:   # 도우인 모달 주소 → 표준 영상 주소
            self._js("dlStatus", "영상 주소 변환 중… (도우인 모달 링크)")
            url = fixed
        cfg = load_config()
        # 설정의 다운로드 폴더 우선 — 비어 있거나 만들 수 없으면 기본 Downloads 로 폴백
        outdir = (cfg.get("dl_outdir") or "").strip() or os.path.join(os.path.expanduser("~"), "Downloads")
        try:
            os.makedirs(outdir, exist_ok=True)
        except Exception:
            outdir = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(outdir, exist_ok=True)
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
        is_insta = bool(re.search(r"instagram\.com/(?:[\w.]+/)?(?:p|reels?|tv)/", url))
        # 인스타는 비로그인 yt-dlp가 막힘 → Apify로 mp4 직접 획득
        if is_insta and cfg.get("apify_token"):
            try:
                self._js("dlStatus", "인스타 영상 주소 조회 중… (Apify)")
                mp4 = apify_post_video(cfg["apify_token"], url)
                m = re.search(r"/(?:p|reels?|tv)/([\w-]+)", url)
                path = os.path.join(outdir, f"instagram_{m.group(1) if m else 'video'}.mp4")
                self._js("dlStatus", "다운로드 중…")
                with requests.get(mp4, stream=True, timeout=120) as r:
                    with open(path, "wb") as f:
                        for ch in r.iter_content(1 << 16):
                            f.write(ch)
                self._js("renderDownload", {"ok": True, "file": os.path.basename(path), "path": path, "dir": outdir})
            except Exception as e:
                self._js("renderDownload", {"ok": False, "error": f"인스타 다운로드 실패: {str(e)[:150]}"})
            return
        # 외부 yt-dlp.exe 우선 (exe 옆 '다운로더' 폴더 — 자가 업데이트 가능), 없으면 내장 라이브러리 폴백
        ext = os.path.join(APP_DIR, "다운로더", "yt-dlp.exe")
        if os.path.exists(ext):
            self._dl_external(ext, url, quality, outdir,
                              cookie_args_for(url, os.path.dirname(ext), cfg)); return
        # yt-dlp (유튜브/틱톡/도우인/샤오홍슈 등 자동 판별)
        def hook(d):
            if d.get("status") == "downloading":
                p = (d.get("_percent_str") or "").strip()
                self._js("dlStatus", f"다운로드 중… {p}")
            elif d.get("status") == "finished":
                self._js("dlStatus", "병합/변환 중… (잠시)")
        opts = {"outtmpl": os.path.join(outdir, "%(title).80s [%(id)s].%(ext)s"),
                "quiet": True, "no_warnings": True, "noprogress": True, "progress_hooks": [hook],
                "extractor_args": {"youtube": {"player_client": ["web_safari", "android", "ios"]}}}
        ck = cookie_args_for(url, os.path.join(APP_DIR, "다운로더"), cfg)
        if ck[:1] == ["--cookies"]:
            opts["cookiefile"] = ck[1]
        elif ck[:1] == ["--cookies-from-browser"]:
            opts["cookiesfrombrowser"] = (ck[1], None, None, None)
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        if quality == "audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
        else:
            h = {"1080": 1080, "720": 720, "480": 480}.get(quality)
            opts["format"] = (f"bestvideo[height<={h}]+bestaudio/best[height<={h}]" if h else "bestvideo+bestaudio/best")
            opts["merge_output_format"] = "mp4"
        self._js("dlStatus", "다운로드 시작…")
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=True)
                path = y.prepare_filename(info)
            if quality == "audio":
                path = os.path.splitext(path)[0] + ".mp3"
            elif not os.path.exists(path):
                base = os.path.splitext(path)[0]
                path = base + ".mp4" if os.path.exists(base + ".mp4") else path
            self._js("renderDownload", {"ok": True, "file": os.path.basename(path), "path": path, "dir": outdir})
        except Exception as e:
            self._js("renderDownload", {"ok": False, "error": dl_error_hint(url, str(e)[:300])})

    # ── 릴스 ──
    def reels_run(self, params):
        threading.Thread(target=self._reels, args=(params,), daemon=True).start()
        return {"ok": True}

    def _reels(self, params):
        cfg = load_config()
        user = params.get("query", "").strip().lstrip("@")
        if not user:
            self._js("reelStatus", "❌ 계정명을 입력하세요"); return
        count = int(params.get("count", 10))
        self._js("reelStatus", "릴스 목록 수집 중… (Apify)")
        try:
            if cfg.get("apify_token"):
                reels = apify_reels(cfg["apify_token"], user, count)
            else:
                self._js("reelStatus", "❌ 설정에 Apify 토큰이 필요합니다 (릴스 수집용·무료). 커뮤니티는 BrightData 사용."); return
        except Exception as e:
            self._js("reelStatus", f"❌ 수집 실패: {str(e)[:140]}"); return
        if not reels:
            self._js("reelStatus", "릴스를 못 찾음 (계정명/공개 여부 확인)"); return
        if not cfg.get("gemini_key"):
            self._js("renderReels", [{**r, "hook": "", "script_ko": "(Gemini 키 필요)", "summary": ""} for r in reels])
            self._js("reelStatus", f"릴스 {len(reels)}개 — 대사 추출엔 Gemini 키 필요"); return
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=cfg["gemini_key"])
        out = []
        for i, r in enumerate(reels):
            self._js("reelStatus", f"대사 추출 {i + 1}/{len(reels)}…")
            try:
                buf = requests.get(r["videoUrl"], timeout=40).content
                resp = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[types.Part.from_bytes(data=buf, mime_type="video/mp4"), REEL_PROMPT])
                out.append({**r, **_parse_json(resp.text)})
            except Exception as e:
                out.append({**r, "hook": "", "script_ko": f"(실패: {str(e)[:60]})", "summary": ""})
        self._js("renderReels", out)
        self._js("reelStatus", f"✅ 완료 — {len(out)}개")

    # ── 소재 추천 ──
    def topic_keywords(self, params):
        threading.Thread(target=self._topic_kw, args=(params,), daemon=True).start()
        return {"ok": True}

    def _topic_kw(self, params):
        cfg = load_config()
        if not cfg.get("gemini_key"):
            self._js("renderKeywords", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return
        self._js("topicStatus", "검색 키워드 추천 생성 중… (Gemini)")
        try:
            seed = (params.get("seed") or "").strip()
            prompt = TOPIC_KW_PROMPT + (f"\n\n특히 이 주제/니치 위주로 확장: {seed}" if seed else "")
            from google import genai
            client = genai.Client(api_key=cfg["gemini_key"])
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=[prompt])
            self._js("renderKeywords", {"ok": True, "keywords": _parse_json_list(resp.text)})
        except Exception as e:
            self._js("renderKeywords", {"ok": False, "error": str(e)[:200]})

    def datalab_cats(self, params):
        return {"ok": True, "cats": datalab_children((params or {}).get("cid", ""))}

    def datalab_run(self, params):
        threading.Thread(target=self._datalab, args=(params,), daemon=True).start()
        return {"ok": True}

    def _datalab(self, params):
        p = params or {}
        cids = p.get("cids") or []
        cid = p.get("cid", "")
        if not cids and not cid:
            self._js("renderKeywords", {"ok": False, "error": "카테고리를 선택하세요."}); return
        try:
            if cids:  # C방식: 여러 카테고리 종합 (리스트)
                kws, seen = [], set()
                for i, c in enumerate(cids):
                    self._js("topicStatus", f"선택 카테고리 수집 {i + 1}/{len(cids)}…")
                    for k in datalab_keywords(c, 30):
                        if k not in seen:
                            seen.add(k); kws.append(k)
                kws = kws[:200]
            elif cid.startswith("ALL"):
                pcid = cid[4:] if cid.startswith("ALL:") else ""
                if not pcid:
                    # 최상위 ★전체 = 12 대분류 상위 (broad, 빠름)
                    cats = [c["cid"] for c in datalab_children("")]
                    note = "대분류 12개"
                else:
                    # 하위 ★전체 = 그 아래 모든 말단(2·3·4분류) 조합, 최대 40개 (시간 제한)
                    leaves = datalab_leaves(pcid)
                    cats = leaves[:40]
                    note = f"세부분류 {len(cats)}개" + (f"(전체 {len(leaves)}개중)" if len(leaves) > len(cats) else "")
                if not cats:
                    self._js("renderKeywords", {"ok": False, "error": "하위 카테고리가 없습니다."}); return
                kws, seen = [], set()
                for i, c in enumerate(cats):
                    self._js("topicStatus", f"전체 수집 {i + 1}/{len(cats)} ({note})…")
                    for k in datalab_keywords(c, 20):
                        if k not in seen:
                            seen.add(k); kws.append(k)
                kws = kws[:200]
            else:
                cnt = int((params or {}).get("count", 100))
                prog = lambda p, t: self._js("topicStatus", f"네이버 데이터랩 인기검색어 가져오는 중… {p}/{t}p")
                kws = datalab_keywords(cid, cnt, progress=prog)
            if not kws:
                self._js("renderKeywords", {"ok": False, "error": "데이터랩 결과 없음 (카테고리/차단 확인)"}); return
            items = [{"keyword": k, "why": f"네이버 데이터랩 인기검색어 {i + 1}위"} for i, k in enumerate(kws)]
            self._js("renderKeywords", {"ok": True, "keywords": items})
        except Exception as e:
            self._js("renderKeywords", {"ok": False, "error": str(e)[:200]})

    def google_trends(self, params):
        threading.Thread(target=self._gtrends, args=(params,), daemon=True).start()
        return {"ok": True}

    def _gtrends(self, params):
        import html as _html
        geo = (params or {}).get("geo", "KR")
        self._js("topicStatus", f"구글 급상승({geo}) 검색어 가져오는 중… (지금 뜨는 이슈)")
        try:
            r = requests.get(f"https://trends.google.com/trending/rss?geo={geo}", timeout=15,
                             headers={"User-Agent": "Mozilla/5.0"})
            titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", r.text, re.S)
            kws, seen = [], set()
            for t in titles[1:]:  # 첫 title은 채널명이라 스킵
                t = _html.unescape(t.strip())
                if t and t not in seen:
                    seen.add(t); kws.append(t)
            if not kws:
                self._js("renderKeywords", {"ok": False, "error": "구글 트렌드 결과 없음"}); return
            items = [{"keyword": k, "why": f"구글 급상승({geo}) · 지금 뜨는 이슈 (컨텐츠 소재)"} for k in kws[:30]]
            self._js("renderKeywords", {"ok": True, "keywords": items})
        except Exception as e:
            self._js("renderKeywords", {"ok": False, "error": str(e)[:200]})

    def topic_run(self, params):
        threading.Thread(target=self._topic, args=(params,), daemon=True).start()
        return {"ok": True}

    def _topic(self, params):
        cfg = load_config()
        if not cfg.get("gemini_key"):
            self._js("renderTopics", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return
        src = params.get("source", "yt")
        query = params.get("query", "").strip()
        try:
            if src == "yt":
                if not cfg.get("youtube_api_key"):
                    self._js("renderTopics", {"ok": False, "error": "설정에 YouTube API 키가 필요합니다."}); return
                if not query:
                    self._js("renderTopics", {"ok": False, "error": "키워드를 입력하세요."}); return
                self._js("topicStatus", "돌연변이 영상 수집 중… (유튜브)")
                rows = yt_collect(cfg["youtube_api_key"], "keyword", query, 40,
                                  params.get("region", "한국"), params.get("period", "90"), "전체")
                rows.sort(key=lambda x: x["outlier"], reverse=True)
                top = rows[:35]
                compact = [{"videoId": r["videoId"], "title": r["title"], "views": r["views"],
                            "outlier": r["outlier"], "likes": r["likes"], "comments": r["comments"]} for r in top]
                self._js("topicStatus", "Gemini 소재 분석 중…")
                cards = self._gemini_topics(cfg, TOPIC_YT_PROMPT, compact)
                # Gemini가 예시를 videoId/제목 섞어 반환 → 실제 영상으로 안전 매핑 (유효한 것만)
                byid = {r["videoId"]: r for r in top}
                bytitle = {r["title"].strip(): r for r in top}
                for c in cards:
                    resolved = []
                    for e in (c.get("examples") or []):
                        r = byid.get(str(e).strip()) or bytitle.get(str(e).strip())
                        if r:
                            resolved.append({"videoId": r["videoId"], "title": r["title"], "link": r["link"]})
                    c["examples"] = resolved
                self._js("renderTopics", {"ok": True, "source": "yt", "cards": cards})
            else:
                sites = params.get("sites") or ["펨코", "디씨"]
                self._js("topicStatus", f"커뮤니티({'/'.join(sites)}) 인기글 수집 중…")
                rows = crawl_community(cfg, sites, pages=int(params.get("pages", 1)))
                if not rows:
                    self._js("renderTopics", {"ok": False, "error": "커뮤니티 글 수집 실패 (프록시/사이트 확인)"}); return
                compact = [{"title": r["title"], "comments": r.get("comments", 0)} for r in rows[:60]]
                self._js("topicStatus", "Gemini 소재 분석 중…")
                cards = self._gemini_topics(cfg, TOPIC_COMM_PROMPT, compact)
                self._js("renderTopics", {"ok": True, "source": "comm", "cards": cards, "videos": {}})
        except Exception as e:
            self._js("renderTopics", {"ok": False, "error": str(e)[:200]})

    def _gemini_topics(self, cfg, prompt, data):
        from google import genai
        client = genai.Client(api_key=cfg["gemini_key"])
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt + "\n\n데이터:\n" + json.dumps(data, ensure_ascii=False)])
        return _parse_json_list(resp.text)

    # ── 각도 발굴 (V7.4 공식) + 소재뱅크 ──
    def angle_run(self, params):
        threading.Thread(target=self._angle, args=(params,), daemon=True).start()
        return {"ok": True}

    def _angle(self, params):
        cfg = load_config()
        if not cfg.get("gemini_key"):
            self._js("renderAngles", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return
        src = params.get("source", "yt")
        query = (params.get("query") or "").strip()
        try:
            if src == "yt":
                if not cfg.get("youtube_api_key"):
                    self._js("renderAngles", {"ok": False, "error": "설정에 YouTube API 키가 필요합니다."}); return
                if not query:
                    self._js("renderAngles", {"ok": False, "error": "키워드를 입력하세요."}); return
                self._js("topicStatus", "🎯 돌연변이 영상 수집 중…")
                rows = yt_collect(cfg["youtube_api_key"], "keyword", query, 40,
                                  params.get("region", "한국"), params.get("period", "90"), "전체")
                rows.sort(key=lambda x: x["outlier"], reverse=True)
                compact = [{"title": r["title"], "views": r["views"], "outlier": r["outlier"]}
                           for r in rows[:35]]
                src_label = f"yt:{query}"
            else:
                sites = params.get("sites") or ["펨코", "디씨"]
                self._js("topicStatus", f"🎯 커뮤니티({'/'.join(sites)}) 인기글 수집 중…")
                rows = crawl_community(cfg, sites, pages=int(params.get("pages", 1)))
                if not rows:
                    self._js("renderAngles", {"ok": False, "error": "커뮤니티 글 수집 실패"}); return
                compact = [{"title": r["title"], "comments": r.get("comments", 0)} for r in rows[:60]]
                src_label = "comm:" + "/".join(sites)
            self._js("topicStatus", "🎯 각도 발굴 중… (V7.4 렌즈·판정)")
            cards = self._gemini_topics(cfg, TOPIC_ANGLE_PROMPT, compact)
            for c in cards:
                c["source"] = src_label
            cards.sort(key=lambda c: -(c.get("score") or 0))
            self._js("renderAngles", {"ok": True, "cards": cards})
        except Exception as e:
            self._js("renderAngles", {"ok": False, "error": str(e)[:200]})

    def bank_list(self):
        return {"ok": True, "items": load_bank()}

    def bank_add(self, params):
        items = load_bank()
        nid = max([i.get("id", 0) for i in items] + [0]) + 1
        added = 0
        for c in (params or {}).get("cards") or []:
            tgt = (c.get("target") or "").strip()
            if not tgt:
                continue
            # 같은 대상+각도는 중복 저장하지 않는다
            if any(i.get("target") == tgt and i.get("angle") == c.get("angle") for i in items):
                continue
            items.append({"id": nid, "ts": datetime.now().strftime("%Y-%m-%d"),
                          "target": tgt, "angle": c.get("angle") or "", "lens": c.get("lens") or 0,
                          "cat": c.get("cat") or 0, "track": c.get("track") or "",
                          "score": c.get("score") or 0, "season": c.get("season") or "",
                          "mystery": c.get("mystery") or "", "source": c.get("source") or "",
                          "status": "대기"})
            nid += 1; added += 1
        save_bank(items)
        return {"ok": True, "added": added, "total": len(items)}

    def bank_set(self, params):
        items = load_bank()
        for i in items:
            if i.get("id") == (params or {}).get("id"):
                i["status"] = (params or {}).get("status") or i["status"]
        save_bank(items)
        return {"ok": True}

    def bank_del(self, params):
        items = [i for i in load_bank() if i.get("id") != (params or {}).get("id")]
        save_bank(items)
        return {"ok": True, "total": len(items)}

    def topic_deep(self, params):
        threading.Thread(target=self._topic_deep, args=(params,), daemon=True).start()
        return {"ok": True}

    def _topic_deep(self, params):
        cfg = load_config()
        cid = params.get("cardId", "")
        vids = params.get("videos", [])  # [{videoId, title}]
        if not cfg.get("gemini_key"):
            self._js("renderTopicDeep", {"cardId": cid, "ok": False, "error": "Gemini 키 필요"}); return
        self._js("topicDeepStatus", {"cardId": cid, "msg": "자막 수집 중…"})
        scripts = []
        for v in vids[:4]:
            txt = yt_transcript(v.get("videoId", ""))
            if txt:
                body = merge_lines(txt.split("\n"))[:3000]
                scripts.append(f"[{v.get('title', '')}]\n{body}")
        if not scripts:
            self._js("renderTopicDeep", {"cardId": cid, "ok": False, "error": "자막 있는 영상이 없음"}); return
        self._js("topicDeepStatus", {"cardId": cid, "msg": "Gemini 심화분석 중…"})
        try:
            from google import genai
            client = genai.Client(api_key=cfg["gemini_key"])
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[TOPIC_DEEP_PROMPT + "\n\n자막:\n" + "\n\n---\n\n".join(scripts)])
            self._js("renderTopicDeep", {"cardId": cid, "ok": True, "analysis": _parse_json_obj(resp.text)})
        except Exception as e:
            self._js("renderTopicDeep", {"cardId": cid, "ok": False, "error": str(e)[:150]})

    # ══════════════════════════════════════════════════════════════
    # 이미지 생성 탭 (PRD_이미지생성탭.md v2)
    # ══════════════════════════════════════════════════════════════
    def get_price_table(self):
        """단가표·모델목록·톤 프리셋을 프론트에 통째로 내려준다 (예상액 계산은 프론트에서)."""
        cfg = load_config()
        ov = cfg.get("img_style_override") or {}
        return {
            "ok": True,
            "models": IMG_MODELS,
            "usd_krw": _num(cfg.get("usd_krw"), 1460),
            "prices": [{"model": m, "size": s, "usd": u, "krw": price_krw(cfg, m, s)}
                       for (m, s), u in PRICE_USD.items()],
            "styles": [{"id": k, "label": STYLE_LABELS.get(k, k), "group": g,
                        "text": ov.get(k) or STYLE_DEFAULTS[k],
                        "custom": bool(ov.get(k))} for g, ks in STYLE_GROUPS for k in ks],
            "spent": cfg.get("img_spent") or {},
            "month": datetime.now().strftime("%Y-%m"),
        }

    def save_style_override(self, params):
        """톤 문구 편집 UI 저장 (PRD 6-4-2a). text가 비면 기본값 복원 = 키 삭제."""
        cfg = load_config()
        ov = dict(cfg.get("img_style_override") or {})
        sid, txt = (params or {}).get("style", ""), ((params or {}).get("text") or "").strip()
        if sid not in STYLE_DEFAULTS:
            return {"ok": False, "error": "알 수 없는 톤"}
        if txt and txt != STYLE_DEFAULTS[sid].strip():
            ov[sid] = txt
        else:
            ov.pop(sid, None)
        cfg["img_style_override"] = ov
        save_config(cfg)
        return {"ok": True, "custom": sid in ov, "text": ov.get(sid) or STYLE_DEFAULTS[sid]}

    def pick_style_refs(self):
        """톤 레퍼런스 이미지 선택 (PRD 6-4-1). 최대 3장, config에 경로로 저장."""
        try:
            files, _ = QFileDialog.getOpenFileNames(
                None, "톤 레퍼런스 이미지 선택 (최대 3장)", "",
                "이미지 (*.png *.jpg *.jpeg *.webp)")
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}
        files = [f for f in (files or []) if os.path.exists(f)][:3]
        cfg = load_config(); cfg["img_style_refs"] = files; save_config(cfg)
        return {"ok": True, "refs": files}

    def clear_style_refs(self):
        cfg = load_config(); cfg["img_style_refs"] = []; save_config(cfg)
        return {"ok": True, "refs": []}

    def pick_char_sheet(self):
        """캐릭터 시트 선택 (anime 톤). 톤 레퍼런스와 **별개 칸**인 이유는 지시문이
        정반대이기 때문이다 — 톤 레퍼런스는 '피사체를 복사하지 마라', 시트는 '이 인물을
        그대로 가져와라'. 한 칸에 섞으면 둘 중 하나가 반드시 깨진다."""
        try:
            files, _ = QFileDialog.getOpenFileNames(
                None, "캐릭터 시트 이미지 선택 (1장)", "",
                "이미지 (*.png *.jpg *.jpeg *.webp)")
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}
        f = next((x for x in (files or []) if os.path.exists(x)), "")
        cfg = load_config(); cfg["char_sheet"] = f; save_config(cfg)
        return {"ok": True, "sheet": f}

    def clear_char_sheet(self):
        cfg = load_config(); cfg["char_sheet"] = ""; save_config(cfg)
        return {"ok": True, "sheet": ""}

    def pick_subject_sheet(self):
        """피사체 시트 선택 — 캐릭터 시트의 사물판. 여러 컷에 같은 구조물·기계·유물을 유지한다.
        보통 이 편에서 먼저 뽑은 이미지 중 그 물건이 가장 잘 나온 한 장을 고른다.
        캐논 문구(글로 적은 묘사)는 컷마다 해석이 달라지지만, 그림은 편차가 훨씬 작다."""
        try:
            files, _ = QFileDialog.getOpenFileNames(
                None, "피사체 시트 이미지 선택 (1장)", "",
                "이미지 (*.png *.jpg *.jpeg *.webp)")
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}
        f = next((x for x in (files or []) if os.path.exists(x)), "")
        cfg = load_config(); cfg["subject_sheet"] = f; save_config(cfg)
        return {"ok": True, "sheet": f}

    def clear_subject_sheet(self):
        cfg = load_config(); cfg["subject_sheet"] = ""; save_config(cfg)
        return {"ok": True, "sheet": ""}

    # ── 📇 등록부 — 인물·사물 개별 등록 + 컷별 선택 참조 (2026-08-19, 할 일 #2) ──
    @staticmethod
    def _reg_dir(cfg, scope, title=""):
        """등록부 그림 폴더 — 인물(perm)은 소스 루트의 _등록부(영구), 사물(ep)은 편 폴더 안."""
        if scope == "ep" and (title or "").strip():
            return os.path.join(project_dir(cfg, title), "등록부")
        base = (cfg.get("img_outdir") or "").strip() or \
            (cfg.get("typecast_outdir") or "").strip() or \
            os.path.join(os.path.expanduser("~"), "Downloads", "쇼츠")
        return os.path.join(base, "_등록부")

    def reg_list(self, params=None):
        cfg = load_config()
        items = []
        for label, e in (cfg.get("registry") or {}).items():
            items.append({"label": label, "desc": e.get("desc") or "",
                          "kind": e.get("kind") or "obj", "scope": e.get("scope") or "perm",
                          "ep": e.get("ep") or "", "path": e.get("path") or "",
                          "ok": bool(e.get("path")) and os.path.exists(e.get("path") or "")})
        items.sort(key=lambda x: (x["kind"] != "char", x["label"]))
        return {"ok": True, "items": items}

    def reg_del(self, params):
        label = ((params or {}).get("label") or "").strip()
        with _CFG_LOCK:
            cfg = load_config()
            reg = dict(cfg.get("registry") or {})
            reg.pop(label, None)
            cfg["registry"] = reg
            save_config(cfg)
        return {"ok": True}

    def reg_promote(self, params):
        """사물(편 단위)을 ⭐영구로 승격 — 그림을 _등록부 로 복사하고 scope 를 바꾼다."""
        import shutil as _sh
        label = ((params or {}).get("label") or "").strip()
        with _CFG_LOCK:
            cfg = load_config()
            reg = dict(cfg.get("registry") or {})
            e = dict(reg.get(label) or {})
            if not e:
                return {"ok": False, "error": "등록된 대상이 아닙니다"}
            src = e.get("path") or ""
            if src and os.path.exists(src):
                d = self._reg_dir(cfg, "perm")
                os.makedirs(d, exist_ok=True)
                dst = os.path.join(d, os.path.basename(src))
                try:
                    _sh.copy2(src, dst)
                    e["path"] = dst
                except Exception:
                    pass
            e["scope"] = "perm"
            reg[label] = e
            cfg["registry"] = reg
            save_config(cfg)
        return {"ok": True}

    def reg_add_file(self, params):
        """내 그림 등록 — 파일 하나를 골라 등록부 폴더로 복사한다 (비용 0)."""
        import shutil as _sh
        p = params or {}
        label = (p.get("label") or "").strip()
        desc = (p.get("desc") or "").strip()
        if not label or not desc:
            return {"ok": False, "error": "라벨과 영어 묘사를 먼저 적어주세요"}
        kind = "char" if (p.get("kind") or "obj") == "char" else "obj"
        scope = p.get("scope") or ("perm" if kind == "char" else "ep")
        try:
            f, _ = QFileDialog.getOpenFileName(
                None, f"[{label}] 그림 선택 (1장)", "",
                "이미지 (*.png *.jpg *.jpeg *.webp)")
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}
        if not f or not os.path.exists(f):
            return {"ok": False, "error": "선택된 파일이 없습니다"}
        cfg = load_config()
        d = self._reg_dir(cfg, scope, p.get("title") or "")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, (_safe_name(label) or "대상") + os.path.splitext(f)[1].lower())
        try:
            _sh.copy2(f, dst)
        except Exception as e:
            return {"ok": False, "error": f"복사 실패: {str(e)[:120]}"}
        with _CFG_LOCK:
            c2 = load_config()
            reg = dict(c2.get("registry") or {})
            reg[label] = {"path": dst, "desc": desc, "kind": kind, "scope": scope,
                          "ep": p.get("title") or ""}
            c2["registry"] = reg
            save_config(c2)
        return {"ok": True, "path": dst}

    def reg_gen(self, params):
        """생성해 등록 — 흰 배경 단독 1장 (대상당 1회 비용). 두 번째 인물부터는 첫 인물
        그림을 화풍 참조로 넣는다 (따로 그리면 서로 닮아버림 — 이식 가이드 08-14 실측)."""
        p = params or {}
        cfg = load_config()
        label = (p.get("label") or "").strip()
        desc = (p.get("desc") or "").strip()
        if not label or not desc:
            return {"ok": False, "error": "라벨과 영어 묘사를 먼저 적어주세요"}
        kind = "char" if (p.get("kind") or "obj") == "char" else "obj"
        scope = p.get("scope") or ("perm" if kind == "char" else "ep")
        # 톤 — 사용자가 고르면 그대로, 안 고르면 배치의 기본 톤(img_style)을 따르고,
        # 그것도 '자동'이면 인물=회색 마네킹 / 사물=제품샷. 등록 그림 화풍이 컷과 어긋나면
        # 참조가 오히려 톤을 흔든다 (2026-08-19 사용자 지적).
        _st = (p.get("style") or "").strip()
        if not _st:
            _st = (cfg.get("img_style") or "").strip()
        if not _st or _st == "auto":
            _st = "greycast" if kind == "char" else "productshot"
        style = norm_style(_st)
        head = ("a single character standing alone, full body, front view, facing the viewer, "
                "on a clean plain white background, nothing else in frame: " if kind == "char"
                else "a single object alone, centered and fully visible, on a clean plain "
                     "white background, nothing else in frame: ")
        cut = {"no": 1, "style": style, "shot": "close" if kind == "char" else "object",
               "beat": "context", "type": "usage", "chars": [], "subject_en": head + desc,
               "place_en": "", "weather_en": "", "motion": "", "anno": "none", "anno_kind": "",
               "focus_en": "", "measure_en": "", "from_en": "", "to_en": "", "flow_of": "",
               "compare_en": "", "anno_label": ""}
        prompt = self._build_prompt(cfg, cut, [], "")
        prompt += ("\n\nAbsolutely no text anywhere, and no second subject in frame. "
                   "Clean plain white background only.")
        ref = []
        if kind == "char":
            for e in (cfg.get("registry") or {}).values():
                if e.get("kind") == "char" and e.get("path") and os.path.exists(e["path"]):
                    ref = [e["path"]]
                    prompt += ("\nMatch the art style, line weight, colouring and body "
                               "proportions of the reference image exactly, but draw a "
                               "DIFFERENT person as described above.")
                    break
        d = self._reg_dir(cfg, scope, p.get("title") or "")
        try:
            os.makedirs(d, exist_ok=True)
            out = self._gen_image(cfg, prompt, ref, "1:1",
                                  os.path.join(d, _safe_name(label) or "대상"),
                                  p.get("model") or cfg.get("img_model") or "gemini-3.1-flash-image",
                                  "2K", rot=0)
        except Exception as e:
            return {"ok": False, "error": self._img_err(str(e))}
        with _CFG_LOCK:
            c2 = load_config()
            reg = dict(c2.get("registry") or {})
            reg[label] = {"path": out, "desc": desc, "kind": kind, "scope": scope,
                          "ep": p.get("title") or ""}
            c2["registry"] = reg
            save_config(c2)
        return {"ok": True, "path": out}

    def char_sheet_prompt(self, params=None):
        """캐릭터 시트 생성용 프롬프트를 조립해 돌려준다 (작품당 1회, 밖에서 뽑아 넣는다).
        시트는 **정면 전신 한 장**이면 된다 — 턴어라운드(좌우·상하 뷰)를 넣으면 모델이
        어느 뷰를 쓸지 헷갈려 컷마다 각도가 섞인다. 중요한 건 A~D 라벨과 흰 배경,
        그리고 인물끼리 머리색·실루엣이 확실히 갈리는 것이다."""
        who = ((params or {}).get("chars") or "").strip()
        return {"ok": True, "prompt": CHAR_SHEET_PROMPT.format(
            chars=who or "(각 인물의 생김새·머리색·옷을 한 줄씩 적으세요)")}

    def img_stop(self):
        self.img_running = False
        return {"ok": True}

    # ── ✂ 자막 재분할 ──
    def sub_split(self, params):
        p = params or {}
        raw = (p.get("srt") or "").strip()
        if not raw:
            return {"ok": False, "error": "SRT 내용을 붙여넣거나 파일을 여세요."}
        blocks = srt_parse(raw)
        est, dropped = False, []
        if not blocks:
            # 타임코드가 없으면 대본으로 보고 글자 수로 시간을 추정한다 — 거절하는 것보다
            # 초안이라도 주는 편이 낫다. 타이밍은 캡컷에서 맞추라고 알린다.
            blocks, dropped = script_to_blocks(raw, _fnum(p.get("cps"), SUB_CPS))
            # 음성 총 길이를 알면 거기에 비례해서 맞춘다 — 타입캐스트 속도 설정과 무관해진다
            blocks = scale_blocks(blocks, _fnum(p.get("total"), 0))
            est = True
        if not blocks:
            return {"ok": False, "error": "쪼갤 자막이 없습니다 — SRT나 대본 텍스트를 넣어주세요."}
        out = fill_gaps(sub_resplit(blocks, int(_num(p.get("max_chars"), 10)),
                                    _fnum(p.get("min_dur"), 0.7), _fnum(p.get("max_dur"), 3.0)))
        return {"ok": True, "before": len(blocks), "after": len(out), "cues": out,
                "srt": srt_build(out), "estimated": est, "dropped": dropped,
                "fitted": bool(est and _num(p.get("total"), 0) > 0),
                "total": round(out[-1]["end"], 1) if out else 0}

    # ── 🎙 타입캐스트 TTS ──
    TC_BASE = "https://api.typecast.ai"
    TC_MAX_CHARS = 1800      # API 상한은 2000자 — 문장 경계로 자를 여유를 둔다

    @staticmethod
    def _tc_headers(cfg):
        return {"X-API-KEY": (cfg.get("typecast_key") or "").strip(),
                "Content-Type": "application/json"}

    def tc_voices(self, params=None):
        """목소리 목록 — 셀렉트를 채운다."""
        cfg = load_config()
        if not (cfg.get("typecast_key") or "").strip():
            return {"ok": False, "error": "설정에 타입캐스트 API 키가 필요합니다."}
        try:
            r = requests.get(f"{self.TC_BASE}/v2/voices",
                             headers=self._tc_headers(cfg),
                             params={"model": cfg.get("typecast_model") or "ssfm-v30"},
                             timeout=30)
            if r.status_code != 200:
                return {"ok": False, "error": f"목소리 목록 실패 ({r.status_code}) {r.text[:160]}"}
            data = r.json()
            items = data if isinstance(data, list) else (data.get("voices") or data.get("data") or [])
            want = cfg.get("typecast_model") or "ssfm-v30"
            out = []
            for v in items:
                vid = v.get("voice_id") or v.get("id")
                if not vid:
                    continue
                # 목소리마다 지원 감정이 다르다 — 감정 셀렉트를 이걸로 채워야 실패하지 않는다
                emo = []
                for mo in (v.get("models") or []):
                    if isinstance(mo, dict) and (not mo.get("model") or mo.get("model") == want):
                        emo += [e for e in (mo.get("emotions") or []) if isinstance(e, str)]
                out.append({"id": vid,
                            "name": v.get("voice_name") or v.get("name") or vid,
                            "gender": v.get("gender") or "", "age": v.get("age") or "",
                            # 쇼츠용 목소리를 골라내는 유일한 단서 — API가 주는 용도 태그
                            "uses": [u for u in (v.get("use_cases") or []) if isinstance(u, str)],
                            "emotions": sorted(set(emo))})
            # 590개가 API 순서대로 오면 사람이 못 찾는다 → 이름순으로 정렬해서 준다
            out.sort(key=lambda x: (x["name"] or "").lower())
            return {"ok": True, "voices": out}
        except Exception as e:
            return {"ok": False, "error": f"목소리 목록 실패: {str(e)[:160]}"}

    def _tc_speak_one(self, cfg, text, seed=0, prev="", nxt=""):
        """한 덩어리를 합성 — (오디오 bytes, 단어 타임스탬프, 길이초, 포맷).

        톤을 붙잡는 세 가지를 함께 보낸다:
          seed          톤을 비슷하게 유지 (완전한 재현은 아니다 — 실측 편차 있음)
          emotion_type  감정을 고정 (비우면 모델이 문장마다 다르게 해석한다)
          previous/next 앞뒤 문맥 — 덩어리 경계에서 말투가 튀는 걸 막는다
        """
        body = {"text": text,
                "voice_id": (cfg.get("typecast_voice") or "").strip(),
                "model": cfg.get("typecast_model") or "ssfm-v30",
                "language": "kor",
                # 캡컷에 넣을 최종 소스라 기본이 wav — mp3 로 받으면 그 순간 이미 한 번
                # 압축되고, 무음 제거가 재인코딩을 한 번 더 얹는다(실측 최대 -0.9dB).
                "output": {"audio_format": tc_format(cfg),
                           "audio_tempo": _fnum(cfg.get("typecast_tempo"), 1.0)}}
        # 음량 통일 — 안 주면 합성할 때마다 볼륨이 조금씩 달라 편끼리 안 맞는다.
        # 유튜브가 -14 LUFS 로 정규화하므로 거기에 맞춰 두면 편집에서 볼륨을 안 만져도 된다.
        # volume 과 함께 못 쓴다(API 제약) → target_lufs 만 보낸다.
        lufs = _fnum(cfg.get("typecast_lufs"), -14.0)
        if -70 <= lufs <= 0:
            body["output"]["target_lufs"] = lufs
        # prompt 는 두 모드 중 하나다 (공식 문서 typecast.ai/docs 기준, 2026-08-08 확인):
        #   emotion_type="preset" → emotion_preset 으로 감정을 고정. 문맥 필드를 못 받는다.
        #   emotion_type="smart"  → previous_text/next_text 로 문맥을 읽어 감정을 스스로 정한다.
        # 둘을 섞으면 422 로 합성이 통째로 실패한다.
        #   ("body.prompt.preset.previous_text — Extra inputs are not permitted")
        # 또 emotion_type 에 감정 이름('normal')을 넣어도 422 다 — 거기는 방식만 온다.
        emo = (cfg.get("typecast_emotion") or "").strip()
        if emo == "auto":          # UI의 '자동' 선택 — 빈 값과 같게 smart 모드로 보낸다
            emo = ""
        if emo:
            body["prompt"] = {"emotion_type": "preset", "emotion_preset": emo}
        elif prev or nxt:
            # 감정을 안 고르면 문맥을 줘서 덩어리 경계에서 말투가 튀는 걸 막는다
            p = {"emotion_type": "smart"}
            if prev:
                p["previous_text"] = prev[-300:]
            if nxt:
                p["next_text"] = nxt[:300]
            body["prompt"] = p
        if seed:
            body["seed"] = int(seed)
        r = requests.post(f"{self.TC_BASE}/v1/text-to-speech/with-timestamps",
                          headers=self._tc_headers(cfg), params={"granularity": "word"},
                          json=body, timeout=180)
        if r.status_code != 200:
            raise RuntimeError(f"합성 실패 ({r.status_code}) {r.text[:200]}")
        d = r.json()
        import base64
        audio = base64.b64decode(d.get("audio") or "")
        words = [w for w in (d.get("words") or []) if (w.get("text") or "").strip()]
        return audio, words, _fnum(d.get("audio_duration"), 0), (d.get("audio_format") or tc_format(cfg))

    def tc_preview(self, params=None):
        """고른 목소리로 짧은 한 문장만 합성해 들려준다.

        590개 중에서 고르려면 들어봐야 하는데, 전에는 대본 전체를 합성해야만 확인이 됐다.
        여기서는 2초짜리 한 문장이라 크레딧이 거의 안 든다.
        """
        p = params or {}
        cfg = load_config()
        if not (cfg.get("typecast_key") or "").strip():
            return {"ok": False, "error": "설정에 타입캐스트 API 키를 넣어주세요."}
        vid = (p.get("voice") or cfg.get("typecast_voice") or "").strip()
        if not vid:
            return {"ok": False, "error": "목소리를 먼저 고르세요."}
        text = (p.get("text") or "안녕하세요. 오늘은 조금 이상한 이야기를 하나 해보겠습니다.").strip()[:120]
        # 화면에서 고른 값을 그대로 반영해 들려준다 (저장 전이라도)
        c2 = dict(cfg, typecast_voice=vid)
        if p.get("emotion") is not None:
            c2["typecast_emotion"] = p.get("emotion") or ""
        if p.get("tempo"):
            c2["typecast_tempo"] = p.get("tempo")
        try:
            audio, _ws, dur, fmt = self._tc_speak_one(c2, text, seed=int(_num(p.get("seed"), 0)))
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
        outdir = (cfg.get("typecast_outdir") or "").strip() or             os.path.join(os.path.expanduser("~"), "Downloads", "쇼츠음성")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, f"_미리듣기.{fmt}")
        with open(path, "wb") as f:
            f.write(audio)
        return {"ok": True, "audio": path, "secs": round(dur, 2), "text": text}

    def tc_speak(self, params):
        """대본 → 음성 + 정확한 자막. 단어 타임스탬프가 실측이라 추정이 없다."""
        p = params or {}
        cfg = load_config()
        if not (cfg.get("typecast_key") or "").strip():
            return {"ok": False, "error": "설정에 타입캐스트 API 키를 넣어주세요."}
        if not (cfg.get("typecast_voice") or "").strip():
            return {"ok": False, "error": "목소리를 먼저 고르세요 ([🔄 목소리 불러오기])."}
        lines, dropped = clean_script_lines(p.get("script") or "")
        if not lines:
            return {"ok": False, "error": "읽을 대본이 없습니다."}
        # API 글자 수 상한에 맞춰 문장 경계로 나눈다 (쇼츠 대본은 대개 한 덩어리)
        pieces, cur = [], ""
        for ln in lines:
            if cur and len(cur) + len(ln) + 1 > self.TC_MAX_CHARS:
                pieces.append(cur); cur = ln
            else:
                cur = (cur + "\n" + ln).strip()
        if cur:
            pieces.append(cur)

        # 영상 한 편 = 폴더 하나. 이 경로를 기억해 두면 뒤이어 만드는 자막·이미지·영상이
        # 같은 자리에 모인다 (예전엔 음성·자막이 저장 폴더 루트에 흩어졌다)
        outdir = project_dir(cfg, p.get("title") or lines[0])
        self._proj_dir = outdir
        # 음성은 자막과 항상 짝으로 쓰이므로 '자막/' 하위에 같이 둔다 (2026-08-12 폴더 정리)
        adir = os.path.join(outdir, "자막")
        try:
            os.makedirs(adir, exist_ok=True)
        except Exception:
            adir = outdir
        # 같은 이름이 있으면 _ver2, _ver3 … — 덮어쓰면 이전 판을 되돌릴 수 없다
        base = uniq_base(os.path.join(adir, "음성"))

        # 시드를 고정하면 톤이 비슷하게 유지된다. 단 완전한 재현은 아니다 (동일 요청 3회 실측 1.99/1.99/2.04초). 지정이 없으면 이번 판을
        # 하나 뽑아 알려준다 — 마음에 들면 그 값을 잠가서 다시 뽑을 수 있게.
        seed = int(_num(p.get("seed"), 0)) or int(_num(cfg.get("typecast_seed"), 0)) \
            or random.randint(1, 2_000_000_000)
        words, parts, off, fmt = [], [], 0.0, tc_format(cfg)
        try:
            for i, piece in enumerate(pieces):
                self._js("subStatus", f"🎙 합성 중… ({i+1}/{len(pieces)})")
                audio, ws, dur, fmt = self._tc_speak_one(
                    cfg, piece, seed=seed,
                    prev=pieces[i - 1] if i else "",
                    nxt=pieces[i + 1] if i + 1 < len(pieces) else "")
                for w in ws:
                    words.append({"text": w.get("text"),
                                  "start": float(w["start"]) + off,
                                  "end": float(w["end"]) + off})
                pth = f"{base}_{i+1}.{fmt}" if len(pieces) > 1 else f"{base}.{fmt}"
                with open(pth, "wb") as f:
                    f.write(audio)
                parts.append(pth)
                off += dur
        except Exception as e:
            return {"ok": False, "error": str(e)[:220]}

        audio_path = parts[0]
        if len(parts) > 1:
            merged = self._concat_audio(parts, f"{base}.{fmt}")
            if merged:
                audio_path = merged
        if not words:
            return {"ok": False, "error": "타임스탬프를 받지 못했습니다 — 목소리·모델을 확인해 주세요."}
        mc = int(_num(p.get("max_chars"), 10))
        cues = words_to_cues(words, mc, _fnum(p.get("min_dur"), 0.7), lines=lines)
        # 짧은 쉼은 앞 자막을 늘려 메운다 — 안 그러면 캡컷에서 클립이 잘게 끊긴다
        out = fill_gaps(sub_resplit(cues, mc, _fnum(p.get("min_dur"), 0.7),
                                    _fnum(p.get("max_dur"), 3.0)))
        # 무음 제거가 쓸 재료 보관 — 단어 타임스탬프가 있어야 자막까지 같이 당길 수 있다
        # lines·seed 는 '문장별 재합성'이 쓴다 — 같은 시드·같은 앞뒤 문맥이라야 톤이 안 튄다
        self._tc_last = {"audio": audio_path, "words": words, "secs": off,
                         "lines": lines, "seed": seed,
                         "max_chars": mc, "min_dur": _fnum(p.get("min_dur"), 0.7),
                         "max_dur": _fnum(p.get("max_dur"), 3.0)}
        return {"ok": True, "cues": out, "srt": srt_build(out), "audio": audio_path,
                "can_trim": True,
                "secs": round(off, 2), "before": len(cues), "after": len(out),
                "dropped": dropped, "estimated": False, "fitted": False, "seed": seed,
                "pieces": len(pieces),
                "emotion": ("" if (cfg.get("typecast_emotion") or "") == "auto"
                            else (cfg.get("typecast_emotion") or "")),
                "total": round(out[-1]["end"], 1) if out else 0}

    # ── 무음 제거 ────────────────────────────────────────────────
    # 말과 말 사이 텀을 잘라 완성본을 짧게 만든다. 핵심은 오디오만 자르면 자막이
    # 통째로 밀린다는 것 — 같은 계산을 단어 타임스탬프에도 적용해 SRT를 다시 만든다.

    @staticmethod
    def _silence_cuts(words, dur, thresh, target):
        """지울 구간 목록. 텀을 완전히 없애지 않고 target 만큼은 남겨 숨 쉴 자리를 둔다."""
        cuts, prev = [], 0.0
        for w in words:
            gap = float(w["start"]) - prev
            if gap > thresh:
                a = prev + target / 2.0
                b = float(w["start"]) - target / 2.0
                if b - a > 0.02:
                    cuts.append((a, b))
            prev = max(prev, float(w["end"]))
        if dur - prev > thresh:                      # 끝에 남는 꼬리 무음
            cuts.append((prev + target, dur))
        return cuts

    @classmethod
    def _silence_cuts_db(cls, src, thresh_db, min_len, target):
        """파형에서 조용한 구간을 찾아 지울 목록을 만든다 (ffmpeg silencedetect).

        단어 타임스탬프 방식(_silence_cuts)과 쓰임이 다르다:
          · 타임스탬프 — 타입캐스트로 **방금 만든** 음성에만 쓸 수 있다. 대신 정확하다.
          · 파형(여기) — 아무 오디오나 된다(직접 녹음·다른 TTS·기존 파일).
            단어 '사이'가 아니라 실제로 소리가 없는 구간을 보므로 숨소리 뒤 정적도 잡는다.
        thresh_db: 이 dB 아래를 무음으로 본다(-35 정도가 일반적, 낮출수록 덜 잡는다)
        min_len:   이보다 긴 무음만 손댄다.  target: 남겨둘 텀(숨 쉴 자리)
        """
        import subprocess
        r = subprocess.run(
            [cls._ffmpeg_exe(), "-i", src, "-af",
             f"silencedetect=noise={thresh_db}dB:d={max(0.05, min_len):.3f}", "-f", "null", "-"],
            capture_output=True, creationflags=0x08000000)
        log = (r.stderr or b"").decode("utf-8", "ignore")
        cuts, start = [], None
        for m in re.finditer(r"silence_(start|end):\s*(-?[\d.]+)", log):
            kind, val = m.group(1), float(m.group(2))
            if kind == "start":
                start = max(0.0, val)
            elif start is not None:
                a, b = start + target / 2.0, val - target / 2.0
                if b - a > 0.02:
                    cuts.append((a, b))
                start = None
        return cuts

    @staticmethod
    def _keep_spans(cuts, dur):
        keeps, pos = [], 0.0
        for a, b in cuts:
            if a > pos:
                keeps.append((pos, a))
            pos = max(pos, b)
        if pos < dur:
            keeps.append((pos, dur))
        return [(a, b) for a, b in keeps if b - a > 0.01]

    # ── 문장별 재합성 ────────────────────────────────────
    # 타입캐스트 단어 토큰은 문장부호를 붙여서 준다("있습니다.") → 줄과 토큰에서
    # **같은 방식으로** 부호를 걷어내야 글자수가 맞는다. 한쪽만 걷어내면 need 가 모자라
    # 쉼표가 많은 줄에서 마지막 단어를 빼먹고 잘린다 (2026-08-08 실측으로 확인).
    _PUNCT = re.compile(r"[\s.,!?~…\"'“”‘’·:;()\[\]<>]")

    @classmethod
    def _line_spans(cls, lines, words):
        """낭독 라인 → (start, end) 시각. 타입캐스트 단어는 입력 순서대로 오므로
        부호·공백을 뺀 글자수를 누적해 경계를 찾는다."""
        spans, wi, n = [], 0, len(words)
        for ln in lines:
            need = len(cls._PUNCT.sub("", ln))
            got, st, en = 0, None, None
            while wi < n and got < need:
                w = words[wi]
                t = cls._PUNCT.sub("", w.get("text") or "")
                if not t:          # 부호만 있는 토큰은 건너뛴다
                    wi += 1
                    continue
                if st is None:
                    st = float(w["start"])
                en = float(w["end"])
                got += len(t)
                wi += 1
            spans.append((st if st is not None else 0.0, en if en is not None else 0.0))
        return spans

    def sub_split_at(self, params):
        """자막 한 줄을 커서 위치에서 둘로 가를 때의 '가르는 시각'을 계산한다 (2026-08-19).
        음성을 이 앱에서 만들었으면 단어별 실측 타임스탬프가 남아 있으므로, 커서 비율과
        가장 가까운 **단어 사이의 실제 틈**으로 스냅한다 — 잘린 두 줄의 시각이 실측이 된다.
        외부 SRT 라 단어 정보가 없으면 글자 수 비례로 폴백한다."""
        p = params or {}
        start = float(_num(p.get("start"), 0))
        dur = max(0.2, float(_num(p.get("dur"), 0)))
        text = p.get("text") or ""
        pos = int(_num(p.get("pos"), 0))
        if pos <= 0 or pos >= len(text.rstrip()):
            return {"ok": False, "error": "줄 처음/끝에서는 가를 수 없습니다 — 커서를 중간에 두세요"}
        end = start + dur
        t = None
        last = getattr(self, "_tc_last", None)
        if last and last.get("words"):
            approx = start + dur * (pos / max(1, len(text)))
            ws = [w for w in last["words"]
                  if float(w.get("start", 0)) >= start - 0.05 and float(w.get("end", 0)) <= end + 0.05]
            best = None
            for w1, w2 in zip(ws, ws[1:]):
                gap = (float(w1["end"]) + float(w2["start"])) / 2.0
                if start + 0.15 < gap < end - 0.15:
                    d = abs(gap - approx)
                    if best is None or d < best[0]:
                        best = (d, gap)
            if best:
                t = best[1]
        if t is None:
            left = len(text[:pos].strip())
            right = len(text[pos:].strip())
            t = start + dur * (left / max(1, left + right))
            t = min(end - 0.15, max(start + 0.15, t))
        return {"ok": True, "t": round(t, 3)}

    def tc_lines(self, params=None):
        """음성을 만든 낭독 라인 목록 + 각 줄의 시각. 문장별 재합성 UI가 쓴다."""
        last = getattr(self, "_tc_last", None)
        if not last or not last.get("lines"):
            return {"ok": False, "error": "먼저 [음성+자막 생성]을 실행하세요."}
        spans = self._line_spans(last["lines"], last["words"])
        rows = [{"i": i, "text": t, "start": round(a, 2), "end": round(b, 2),
                 "dur": round(b - a, 2)}
                for i, (t, (a, b)) in enumerate(zip(last["lines"], spans))]
        return {"ok": True, "rows": rows, "secs": round(float(last["secs"]), 2),
                "seed": last.get("seed", 0)}

    def tc_respeak(self, params):
        """한 줄만 다시 합성해 원본 오디오에 끼워 넣는다.

        같은 시드·같은 목소리·앞뒤 문맥을 그대로 보내 톤이 튀지 않게 하고,
        길이가 달라진 만큼 뒤쪽 단어 타임스탬프를 밀어 자막 싱크를 유지한다.
        """
        p = params or {}
        last = getattr(self, "_tc_last", None)
        if not last or not last.get("lines"):
            return {"ok": False, "error": "먼저 [음성+자막 생성]을 실행하세요."}
        try:
            idx = int(_num(p.get("index"), -1))
        except Exception:
            idx = -1
        lines = list(last["lines"])
        if not (0 <= idx < len(lines)):
            return {"ok": False, "error": "고칠 줄을 고르세요."}
        new_text = (p.get("text") or "").strip()
        if not new_text:
            return {"ok": False, "error": "새 문장을 입력하세요."}

        cfg = load_config()
        spans = self._line_spans(lines, last["words"])
        a, b = spans[idx]
        if b <= a:
            return {"ok": False, "error": "그 줄의 구간을 찾지 못했습니다. 전체 재생성이 필요합니다."}

        try:
            audio, ws, dur, fmt = self._tc_speak_one(
                cfg, new_text, seed=int(_num(last.get("seed"), 0)),
                prev=lines[idx - 1] if idx else "",
                nxt=lines[idx + 1] if idx + 1 < len(lines) else "")
        except Exception as e:
            return {"ok": False, "error": f"재합성 실패: {str(e)[:180]}"}

        src = last["audio"]
        tmp = os.path.join(os.path.dirname(src), f"_respeak_{idx}.{fmt}")
        with open(tmp, "wb") as f:
            f.write(audio)
        total = float(last["secs"])
        out = os.path.join(os.path.dirname(src),
                           os.path.splitext(os.path.basename(src))[0] + "_edit.mp3")
        # [앞부분][새 문장][뒷부분] 이어붙이기
        parts, graph, k = [], "", 0
        if a > 0.02:
            graph += f"[0:a]atrim=0:{a:.3f},asetpts=N/SR/TB[s{k}];"; parts.append(f"[s{k}]"); k += 1
        graph += f"[1:a]asetpts=N/SR/TB[s{k}];"; parts.append(f"[s{k}]"); k += 1
        if total - b > 0.02:
            graph += f"[0:a]atrim={b:.3f}:{total:.3f},asetpts=N/SR/TB[s{k}];"; parts.append(f"[s{k}]"); k += 1
        graph += "".join(parts) + f"concat=n={len(parts)}:v=0:a=1[out]"
        try:
            r = subprocess.run([self._ffmpeg_exe(), "-y", "-i", src, "-i", tmp,
                                "-filter_complex", graph, "-map", "[out]",
                                "-b:a", "192k", "-ar", "44100", out],
                               capture_output=True, creationflags=0x08000000)
            if r.returncode != 0 or not os.path.exists(out):
                return {"ok": False, "error": "ffmpeg 실패: " + (r.stderr or b"")[-200:].decode("utf-8", "ignore")}
        except Exception as e:
            return {"ok": False, "error": f"ffmpeg 실행 실패: {str(e)[:150]}"}
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass

        # 타임스탬프 재구성 — 앞은 그대로, 새 문장은 a 기준, 뒤는 길이 차이만큼 이동
        delta = dur - (b - a)
        words = []
        for w in last["words"]:
            st, en = float(w["start"]), float(w["end"])
            if en <= a + 1e-6:
                words.append({"text": w["text"], "start": st, "end": en})
            elif st >= b - 1e-6:
                words.append({"text": w["text"], "start": st + delta, "end": en + delta})
        ins = [{"text": w.get("text"), "start": float(w["start"]) + a, "end": float(w["end"]) + a}
               for w in ws]
        words = [w for w in words if w["end"] <= a + 1e-6] + ins +                 [w for w in words if w["start"] >= a + (b - a) + delta - 1e-6]
        words.sort(key=lambda w: w["start"])

        lines[idx] = new_text
        mc, mind, maxd = last["max_chars"], last["min_dur"], last["max_dur"]
        cues = fill_gaps(sub_resplit(words_to_cues(words, mc, mind, lines=lines), mc, mind, maxd))
        self._tc_last = dict(last, audio=out, words=words, lines=lines, secs=total + delta)
        return {"ok": True, "cues": cues, "srt": srt_build(cues), "audio": out,
                "secs": round(total + delta, 2), "before": round(total, 2),
                "delta": round(delta, 2), "index": idx, "text": new_text}

    def tc_trim_silence(self, params=None):
        p = params or {}
        last = getattr(self, "_tc_last", None)
        if not last or not last.get("words"):
            return {"ok": False, "error": "먼저 [🎙 음성+자막 생성]으로 음성을 만들어 주세요."}
        src = last["audio"]
        if not os.path.exists(src):
            return {"ok": False, "error": "음성 파일을 찾을 수 없습니다. 다시 생성해 주세요."}

        thresh = _fnum(p.get("thresh"), 0.25)   # 이보다 긴 텀만 손댄다
        target = _fnum(p.get("target"), 0.12)   # 남겨둘 텀
        words, dur = last["words"], float(last["secs"])
        # 두 가지로 무음을 찾는다. 단어 타임스탬프는 '말과 말 사이'만 보므로 낭독이 촘촘하면
        # 아무것도 못 찾는다(실측 2026-08-11: 44초 음성에서 250ms 넘는 텀 0곳). 파형(dB)은
        # 실제로 소리가 없는 구간을 보므로 같은 파일에서 8곳 1.4초를 잡아냈다.
        if (p.get("mode") or "words") == "db":
            cuts = self._silence_cuts_db(src, _fnum(p.get("db"), -35), thresh, target)
            miss = f"{_fnum(p.get('db'), -35):.0f}dB 아래로 조용한 구간이 없습니다 — 강도를 올려보세요."
        else:
            cuts = self._silence_cuts(words, dur, thresh, target)
            miss = (f"{int(thresh*1000)}ms 넘는 텀이 없습니다 — 자를 게 없습니다. "
                    "숨소리·잡음까지 잡으려면 [파형(dB)] 방식을 써보세요.")
        if not cuts:
            return {"ok": False, "error": miss}
        keeps = self._keep_spans(cuts, dur)
        if not keeps:
            return {"ok": False, "error": "남는 구간이 없습니다. 강도를 낮춰주세요."}

        stem, ext = os.path.splitext(src)
        out = f"{stem}_무음제거{ext}"
        parts = "".join(
            f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=N/SR/TB[s{i}];"
            for i, (a, b) in enumerate(keeps))
        graph = (parts + "".join(f"[s{i}]" for i in range(len(keeps)))
                 + f"concat=n={len(keeps)}:v=0:a=1[out]")
        try:
            import subprocess
            # 필터를 거치면 무조건 재인코딩된다 → 비트레이트를 명시하지 않으면
            # 원본보다 낮게 잡혀 음질이 떨어진다. 음성이라 192k면 충분하고 원본 손실이 없다.
            # mp3 → mp3 재인코딩은 손실이 한 번 더 쌓인다(실측 최대 -0.9 dB).
            # 캡컷에 넣을 거면 wav 가 안전하다 — 파일은 크지만 손실이 0이다.
            wav = bool(p.get("wav")) or (cfg.get("tc_trim_wav") in (True, "1", 1))
            if wav:
                out = os.path.splitext(out)[0] + ".wav"
                enc = ["-c:a", "pcm_s16le", "-ar", "44100"]
            else:
                enc = ["-b:a", "192k", "-ar", "44100"]
            r = subprocess.run([self._ffmpeg_exe(), "-y", "-i", src,
                                "-filter_complex", graph, "-map", "[out]"] + enc + [out],
                               capture_output=True, creationflags=0x08000000)
            if r.returncode != 0 or not os.path.exists(out):
                return {"ok": False, "error": "ffmpeg 실패: " + (r.stderr or b"")[-200:].decode("utf-8", "ignore")}
        except Exception as e:
            return {"ok": False, "error": f"ffmpeg 실행 실패: {str(e)[:150]}"}

        # 같은 계산으로 타임스탬프를 당겨 자막을 새 타임라인에 다시 얹는다
        def shift(t):
            t = float(t)
            return t - sum(min(b, t) - a for a, b in cuts if a < t)

        new_words = [{"text": w["text"], "start": shift(w["start"]), "end": shift(w["end"])}
                     for w in words]
        mc, mind, maxd = last["max_chars"], last["min_dur"], last["max_dur"]
        # 대본 줄바꿈을 반드시 넘긴다. 무음을 걷어내면 문장 사이 쉼도 같이 사라져서
        # gap_split(낭독의 쉼) 단서가 통째로 죽는다 — 음슴체는 마침표도 없으니 줄바꿈이
        # 남은 유일한 문장 경계다. 안 넘기면 "실어버린 거 비결은 성분이"처럼 두 문장이
        # 한 줄에 섞인다 (2026-08-11 제보).
        cues = fill_gaps(sub_resplit(
            words_to_cues(new_words, mc, mind, lines=last.get("lines")), mc, mind, maxd))
        removed = sum(b - a for a, b in cuts)

        self._tc_last = dict(last, audio=out, words=new_words, secs=dur - removed)
        return {"ok": True, "cues": cues, "srt": srt_build(cues), "audio": out,
                "secs": round(dur - removed, 2), "before": round(dur, 2),
                "removed": round(removed, 2), "spots": len(cuts)}

    # ── 목소리 프리셋 ────────────────────────────────────────────
    # 목소리·속도·감정·시드는 한 세트로 굴러야 톤이 유지된다. 매번 다시 고르지 않게 저장해둔다.

    def tc_presets(self, params=None):
        return {"ok": True, "presets": load_config().get("tc_voice_presets", [])}

    def tc_preset_save(self, params):
        p = params or {}
        name = (p.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "프리셋 이름을 입력하세요."}
        if not (p.get("voice") or "").strip():
            return {"ok": False, "error": "목소리를 먼저 고르세요."}
        cfg = load_config()
        lst = [x for x in cfg.get("tc_voice_presets", []) if x.get("name") != name]
        lst.append({"name": name, "voice": p.get("voice", ""), "voice_name": p.get("voice_name", ""),
                    "tempo": p.get("tempo", "1"), "emotion": p.get("emotion", ""),
                    "seed": p.get("seed", "")})
        cfg["tc_voice_presets"] = lst[-30:]
        save_config(cfg)
        return {"ok": True, "presets": cfg["tc_voice_presets"]}

    def tc_preset_del(self, params):
        name = ((params or {}).get("name") or "").strip()
        cfg = load_config()
        cfg["tc_voice_presets"] = [x for x in cfg.get("tc_voice_presets", []) if x.get("name") != name]
        save_config(cfg)
        return {"ok": True, "presets": cfg["tc_voice_presets"]}

    def _concat_audio(self, parts, out):
        """여러 조각을 하나로 (ffmpeg concat). 실패하면 None — 조각 파일은 그대로 남는다."""
        try:
            import subprocess
            lst = out + ".txt"
            with open(lst, "w", encoding="utf-8") as f:
                for p in parts:
                    f.write("file '" + p.replace("\\", "/").replace("'", "'\\''") + "'\n")
            r = subprocess.run([self._ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0",
                                "-i", lst, "-c", "copy", out],
                               capture_output=True, creationflags=0x08000000)
            try:
                os.remove(lst)
            except Exception:
                pass
            return out if (r.returncode == 0 and os.path.exists(out)) else None
        except Exception:
            return None

    def audio_duration(self, params=None):
        """음성 파일을 골라 길이(초)를 읽는다 — 추정 자막을 실제 길이에 맞추는 용도."""
        p = params or {}
        path = (p.get("path") or "").strip()
        if not path:
            try:
                from PySide6.QtWidgets import QFileDialog
                base = (load_config().get("img_outdir") or "").strip() or \
                    os.path.join(os.path.expanduser("~"), "Downloads")
                path, _ = QFileDialog.getOpenFileName(
                    None, "음성 파일 선택", base,
                    "오디오·영상 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mov);;모든 파일 (*.*)")
            except Exception as e:
                return {"ok": False, "error": f"파일 선택 실패: {str(e)[:120]}"}
        if not path or not os.path.exists(path):
            return {"ok": False, "error": "파일을 고르지 않았습니다."}
        try:
            import subprocess
            ff = self._ffmpeg_exe()
            r = subprocess.run([ff, "-i", path], capture_output=True,
                               creationflags=0x08000000)   # CREATE_NO_WINDOW
            # ffmpeg 는 입력만 주면 오류로 끝나지만 stderr 에 Duration 을 찍는다
            m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d+)",
                          r.stderr.decode("utf-8", "ignore"))
            if not m:
                return {"ok": False, "error": "길이를 읽지 못했습니다 — 다른 형식으로 시도해 주세요."}
            secs = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                    + float("0." + m.group(4)))
            return {"ok": True, "secs": round(secs, 2), "name": os.path.basename(path)}
        except Exception as e:
            return {"ok": False, "error": f"길이 읽기 실패: {str(e)[:120]}"}

    def sub_save(self, params):
        p = params or {}
        txt = p.get("srt") or ""
        try:
            from PySide6.QtWidgets import QFileDialog
            # 이번 세션에서 음성을 만들었으면 그 프로젝트의 '자막/' 폴더가 기본값 — 음성과 짝으로 모인다
            pd = getattr(self, "_proj_dir", "")
            if pd:
                base = os.path.join(pd, "자막")
                try:
                    os.makedirs(base, exist_ok=True)
                except Exception:
                    base = pd
            else:
                base = (load_config().get("img_outdir") or "").strip() or \
                    os.path.join(os.path.expanduser("~"), "Downloads")
            path, _ = QFileDialog.getSaveFileName(None, "자막 저장",
                                                  os.path.join(base, "자막.srt"), "SRT (*.srt)")
            if not path:
                return {"ok": False, "error": "취소됨"}
            with open(path, "w", encoding="utf-8-sig") as f:   # 캡컷은 BOM 있는 UTF-8 을 잘 읽는다
                f.write(txt)
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}

    def sub_open(self):
        try:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(None, "SRT 열기", "", "자막 (*.srt *.vtt *.txt)")
            if not path:
                return {"ok": False}
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    with open(path, encoding=enc) as f:
                        return {"ok": True, "srt": f.read(), "name": os.path.basename(path)}
                except UnicodeDecodeError:
                    continue
            return {"ok": False, "error": "인코딩을 읽지 못했습니다"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}

    # ── 🔬 원본 분석 — 레퍼런스 영상을 컷 단위로 역설계 ──
    def analyze_video(self, params):
        if getattr(self, "anz_running", False):
            return {"ok": False, "error": "이미 분석 중입니다."}
        self.anz_running = True
        threading.Thread(target=self._analyze_video, args=(params,), daemon=True).start()
        return {"ok": True}

    def analyze_stop(self):
        self.anz_running = False
        return {"ok": True}

    def _analyze_video(self, params):
        try:
            self._analyze_video_body(params)
        finally:
            self.anz_running = False

    def _analyze_video_body(self, params):
        import base64, subprocess, tempfile, shutil
        p = params or {}
        cfg = load_config()
        url = (p.get("url") or "").strip()
        maxc = int(_num(p.get("max_cuts"), 12))
        if not url:
            self._js("anzDone", {"ok": False, "error": "영상 URL 또는 파일 경로를 넣으세요."}); return
        if not cfg.get("gemini_key"):
            self._js("anzDone", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return

        work = os.path.join(tempfile.gettempdir(), f"anz_{os.getpid()}_{threading.get_ident()}")
        os.makedirs(work, exist_ok=True)
        ff = self._ffmpeg_exe()
        try:
            # ① 영상 확보 — 로컬 파일이면 그대로, URL 이면 yt-dlp 로 받는다
            if os.path.exists(url):
                src = os.path.join(work, "src" + (os.path.splitext(url)[1] or ".mp4"))
                shutil.copyfile(url, src)
            else:
                self._js("anzStatus", "영상 내려받는 중…")
                ytd = os.path.join(APP_DIR, "다운로더", "yt-dlp.exe")
                src = os.path.join(work, "src.mp4")
                if not os.path.exists(ytd):
                    self._js("anzDone", {"ok": False, "error": "다운로더 폴더의 yt-dlp.exe 가 필요합니다."}); return
                subprocess.run([ytd, "-f", "bv*[height<=1280]+ba/b", "--merge-output-format", "mp4",
                                "-o", src, "--no-playlist", url],
                               capture_output=True, timeout=600, creationflags=0x08000000)
                if not os.path.exists(src):
                    cand = [f for f in os.listdir(work) if f.startswith("src.")]
                    if not cand:
                        self._js("anzDone", {"ok": False, "error": "영상을 받지 못했습니다 (URL 확인)"}); return
                    src = os.path.join(work, cand[0])

            # ② 컷 전환 감지 — 장면 변화량 기준
            self._js("anzStatus", "컷 전환 감지 중…")
            r = subprocess.run([ff, "-i", src, "-vf", "select='gt(scene,0.25)',showinfo", "-f", "null", "-"],
                               capture_output=True, text=True, encoding="utf-8", errors="ignore",
                               timeout=900, creationflags=0x08000000)
            times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr or "")]
            dur = 0.0
            m = re.search(r"Duration: (\d+):(\d+):([0-9.]+)", r.stderr or "")
            if m:
                dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            starts = [0.0] + times
            starts = [t for t in starts if t < max(dur - 0.4, 0.4)]
            # 컷이 너무 많으면 긴 컷 위주로 추린다 (분석 비용·시간 제어)
            segs = []
            for i, st in enumerate(starts):
                en = starts[i + 1] if i + 1 < len(starts) else dur
                segs.append((st, max(en - st, 0.1), i + 1))
            if len(segs) > maxc:
                segs = sorted(sorted(segs, key=lambda s: -s[1])[:maxc], key=lambda s: s[0])

            # ③ 컷마다 시작·중간·끝 3프레임 → 카메라/모션 판단 근거
            self._js("anzStatus", f"컷 {len(segs)}개 · 프레임 추출 중…")
            shots = []
            for st, ln, no in segs:
                if not self.anz_running:
                    self._js("anzDone", {"ok": False, "error": "중단됨"}); return
                tile = os.path.join(work, f"c{no:03d}.jpg")
                subprocess.run([ff, "-y", "-ss", f"{st:.2f}", "-t", f"{min(ln, 12):.2f}", "-i", src,
                                "-vf", f"fps={max(3.0/max(ln,0.4),0.34):.3f},scale=340:-1,tile=3x1",
                                "-frames:v", "1", "-q:v", "3", tile],
                               capture_output=True, timeout=180, creationflags=0x08000000)
                if os.path.exists(tile):
                    shots.append({"no": no, "start": round(st, 2), "len": round(ln, 2), "tile": tile})

            if not shots:
                self._js("anzDone", {"ok": False, "error": "프레임을 추출하지 못했습니다."}); return

            # ④ Gemini Vision 으로 컷별 역설계
            from google import genai
            from google.genai import types as gtypes
            client = genai.Client(api_key=cfg["gemini_key"])
            results = []
            for i, s in enumerate(shots, 1):
                if not self.anz_running:
                    break
                self._js("anzStatus", f"({i}/{len(shots)}) #{s['no']} 컷 분석 중… (Gemini Vision)")
                with open(s["tile"], "rb") as f:
                    img = f.read()
                try:
                    resp = client.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=[gtypes.Part.from_bytes(data=img, mime_type="image/jpeg"),
                                  ANALYZE_PROMPT.format(secs=s["len"])])
                    d = _parse_obj(resp.text) or {}
                except Exception as e:
                    d = {"error": str(e)[:120]}
                d["no"] = s["no"]; d["start"] = s["start"]; d["len"] = s["len"]
                try:
                    d["thumb"] = "data:image/jpeg;base64," + base64.b64encode(img).decode()
                except Exception:
                    d["thumb"] = ""
                # 우리 프리셋으로 정규화 — 분석 결과를 바로 앱에 옮길 수 있게
                d["style"] = norm_style(d.get("style"))
                d["camera"] = norm_camera(d.get("camera"), "push")
                results.append(d)
                self._js("anzCut", d)

            self._js("anzDone", {"ok": True, "count": len(results), "total_cuts": len(starts),
                                 "duration": round(dur, 1),
                                 "avg": round(dur / max(len(starts), 1), 2)})
        except Exception as e:
            self._js("anzDone", {"ok": False, "error": str(e)[:200]})
        finally:
            try:
                shutil.rmtree(work, ignore_errors=True)
            except Exception:
                pass

    # ── 컷 분해 임시저장 (UI가 수시로 저장 → 재시작 시 복원 제안) ──
    def save_cut_draft(self, params):
        # 임시파일에 쓴 뒤 os.replace로 원자 교체 — 저장 도중 앱이 죽어도 이전 저장본이 살아남는다
        tmp = DRAFT_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(params or {}, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, DRAFT_FILE)
            return {"ok": True}
        except Exception as e:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return {"ok": False, "error": str(e)[:120]}

    def load_cut_draft(self):
        try:
            if not os.path.exists(DRAFT_FILE):
                return {"ok": True, "draft": None}
            with open(DRAFT_FILE, encoding="utf-8") as f:
                return {"ok": True, "draft": json.load(f)}
        except Exception as e:
            # 파손 파일은 .bad로 치워 다음 저장을 막지 않게 하고, 프론트에 손상 사실을 알린다
            try:
                os.replace(DRAFT_FILE, DRAFT_FILE + ".bad")
            except Exception:
                pass
            return {"ok": False, "error": str(e)[:120]}

    def clear_cut_draft(self):
        try:
            if os.path.exists(DRAFT_FILE):
                os.remove(DRAFT_FILE)
        except Exception:
            pass
        return {"ok": True}

    # ── 한글 묘사 → 영문 프롬프트 변환 (컷 카드 🌐 버튼) ──
    def ko_to_prompt(self, params):
        threading.Thread(target=self._ko_to_prompt, args=(params,), daemon=True).start()
        return {"ok": True}

    def _ko_to_prompt(self, params):
        cfg = load_config()
        p = params or {}
        ko, no = (p.get("ko") or "").strip(), p.get("no")
        kind = p.get("kind") or "subject"   # subject: 이미지 프롬프트 / motion: 영상 모션 문장
        if not ko:
            self._js("ko2enDone", {"ok": False, "no": no, "kind": kind, "error": "한글 묘사가 비어 있습니다."}); return
        if not cfg.get("gemini_key"):
            self._js("ko2enDone", {"ok": False, "no": no, "kind": kind, "error": "설정에 Gemini 키가 필요합니다."}); return
        if kind == "motion":
            # 분해기의 motion_en 규격과 동일 — 시간에 따라 무엇이 변하는지, 카메라 언급 금지
            prompt = ("Rewrite the following Korean description of how a scene changes over time "
                      "as ONE concrete English motion sentence for AI video generation. "
                      "Use physical verbs (melts, cracks, floods, hardens, pours, collapses) and "
                      "state what changes from start to end. Do not mention camera movement, "
                      "style or lighting. Output only the sentence, no quotes.\n\n" + ko[:1000])
        else:
            # 분해기의 subject_en 규격과 동일하게 — 재질·색·상태까지 구체적인 한 문장
            prompt = ("Rewrite the following Korean scene description as ONE concrete English "
                      "image-generation prompt sentence. Be specific about the subject, materials, "
                      "colors and physical state. Do not mention style, camera or lighting. "
                      "Output only the sentence, no quotes, no explanations.\n\n" + ko[:1000])
        try:
            from google import genai
            client = genai.Client(api_key=cfg["gemini_key"])
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=[prompt])
            en = (resp.text or "").strip().strip('"').strip()
            if not en:
                raise RuntimeError("빈 응답")
            self._js("ko2enDone", {"ok": True, "no": no, "kind": kind, "en": en})
        except Exception as e:
            self._js("ko2enDone", {"ok": False, "no": no, "kind": kind, "error": str(e)[:150]})

    def _split_claude(self, cfg, prompt):
        """Claude Opus 컷 분해. 과부하(529)는 잠깐 쉬면 풀리므로 재시도하고,
        그래도 안 되면 None → 호출부가 Gemini 로 폴백한다. 스트리밍은 타임아웃 방지용.

        (data, 입력토큰, 출력토큰) 을 돌려준다 — 실제 청구는 응답이 준 토큰 수로만 알 수 있고,
        누른 뒤 얼마 나갔는지 보여주려면 그 값이 필요하다.

        실패 사유는 self._split_claude_err 에 남긴다. 예전엔 이유 없이 "실패 — 폴백"만 떠서,
        **크레딧이 떨어져 몇 주째 Gemini 로 돌고 있어도 알 수 없었다** (2026-08-13 실측).
        크레딧·키 문제는 재시도해도 안 풀리므로 즉시 접고 사유를 남긴다."""
        import anthropic
        self._split_claude_err = ""
        client = anthropic.Anthropic(api_key=(cfg.get("anthropic_key") or "").strip())
        for attempt in range(3):
            try:
                with client.messages.stream(model="claude-opus-5", max_tokens=32000,
                                            messages=[{"role": "user", "content": prompt}]) as s:
                    resp = s.get_final_message()
                txt = "".join(b.text for b in resp.content if b.type == "text")
                u = getattr(resp, "usage", None)
                tin, tout = (getattr(u, "input_tokens", 0) or 0), (getattr(u, "output_tokens", 0) or 0)
                data = _parse_cuts(txt)
                if data:
                    return data, tin, tout
                self._split_claude_err = "응답을 JSON 으로 읽지 못함"
                # 파싱 실패 — 같은 값으로 한 번 더 (Gemini 쪽 재시도 정책과 동일)
            except Exception as e:
                msg = str(e)
                if any(k in msg for k in ("529", "overloaded", "429", "500", "503")):
                    self._split_claude_err = "Claude 서버 과부하"
                    time.sleep(8 * (attempt + 1))
                    continue
                low = msg.lower()
                if "credit balance is too low" in low:
                    self._split_claude_err = ("Anthropic 크레딧 잔액 부족 — console.anthropic.com "
                                              "의 Plans & Billing 에서 충전해야 Opus 로 분해됩니다")
                elif "authentication" in low or "invalid x-api-key" in low or "401" in msg:
                    self._split_claude_err = "Anthropic 키가 올바르지 않습니다 (설정 탭에서 확인)"
                elif "not_found" in low or "model" in low and "404" in msg:
                    self._split_claude_err = "이 키로는 claude-opus-5 를 쓸 수 없습니다"
                else:
                    self._split_claude_err = msg[:120]
                return None, 0, 0
        return None, 0, 0

    # ── ① 컷 분해 ──
    def split_script(self, params):
        threading.Thread(target=self._split_script, args=(params,), daemon=True).start()
        return {"ok": True}

    def split_guide(self, params=None):
        """claude.ai 에 붙여넣을 지침. API 로 보내는 것과 **같은 원문**을 쓰되 기계용
        자리(컷 수·글자 수 플레이스홀더)만 사람이 읽는 값으로 바꾼다.
        지침을 두 벌 관리하면 반드시 한쪽만 고쳐지고, 그때부터 둘의 결과가 갈린다."""
        cfg = load_config()
        cps = 8.7 * max(0.5, _fnum(cfg.get("typecast_tempo"), 1.0))
        body = SCENE_SPLIT_PROMPT
        body = body[body.index("[0. 대본 형식"):body.rindex("[대본]")].rstrip()
        body = (body.replace("{n_cuts}", "아래 계산식으로 구한 수")
                    .replace("{chars_lo}", str(int(cps * 4)))
                    .replace("{chars_hi}", str(int(cps * 8)))
                    .replace("{{", "{").replace("}}", "}"))
        # 내용 해시 — 올려둔 파일이 최신인지 대조할 유일한 수단이다. 날짜를 쓰면 복사할
        # 때마다 바뀌어 "내용이 바뀐 것"과 "그냥 다시 뽑은 것"을 구분할 수 없다.
        import hashlib
        ver = hashlib.sha1(body.encode("utf-8")).hexdigest()[:8]
        head = (f"<!-- 지침 버전 {ver} — 앱의 [📋 지침 복사] 로 다시 뽑아 교체하세요 -->\n\n"
                f"당신은 유튜브 쇼츠 채널의 이미지 디렉터다.\n"
                f"사용자가 **\"컷 분해해줘\"** 라고 말할 때만 이 지침을 쓴다 — 평소 대본 요청에는 꺼내지 않는다.\n"
                f"방금 쓴 대본을 화면에 깔 정지 이미지 컷으로 분해하고, **JSON 하나만** 코드블록에 담아 출력한다.\n"
                f"설명·머리말·요약을 붙이지 마라 — 그대로 앱에 붙여넣는다.\n\n"
                f"[컷 수 계산]\n"
                f"공백 뺀 글자 수 ÷ {int(cps * 5.5)} = 컷 수(반올림). ±2컷 안에서 흐름이 맞는 자리를 골라라.\n"
                f"문장 수로 세지 마라 — 짧은 문장 대본에서 2초짜리 컷이 쏟아진다.\n\n"
                f"[네가 채우는 것은 짧은 값뿐이다]\n"
                f"완성된 영어 프롬프트를 쓰지 마라. 앱이 이 값들로 약 3,500자짜리 프롬프트를 조립한다.\n"
                f"질감·색·카메라·강조 문법은 앱이 갖고 있고, 그래야 편마다 같은 결로 나온다.\n\n")
        return {"ok": True, "text": head + body}

    def split_paste(self, params):
        """claude.ai 에서 받은 JSON 을 API 결과와 **같은 길**로 흘려보낸다.
        정규화(강조 게이팅·캐논·컷 길이 배정)가 전부 _split_script 안에 있어서,
        여기서 따로 파싱하면 그 검사를 통째로 건너뛰게 된다."""
        threading.Thread(target=self._split_script, args=(params,), daemon=True).start()
        return {"ok": True}

    def _split_script(self, params):
        cfg = load_config()
        script = ((params or {}).get("script") or "").strip()
        # 붙여넣기 경로 — 모델을 부르지 않고 준 JSON 을 그대로 정규화 단계로 넘긴다
        pasted = (params or {}).get("pasted")
        if pasted:
            try:
                txt = pasted.strip()
                m = re.search(r"```(?:json)?\s*(.+?)```", txt, re.S)   # 코드블록째 붙여넣어도 받는다
                if m:
                    txt = m.group(1).strip()
                i, j = txt.find("{"), txt.rfind("}")
                data = json.loads(txt[i:j + 1] if i >= 0 and j > i else txt)
            except Exception as e:
                self._js("renderCuts", {"ok": False,
                                        "error": f"JSON 을 읽지 못했습니다 — {e}"}); return
            if not (data.get("cuts") or []):
                self._js("renderCuts", {"ok": False, "error": "cuts 배열이 비어 있습니다."}); return
            self._finish_split(cfg, data, "paste", {"opus": [0, 0], "gemini": [0, 0]}); return
        if not script:
            self._js("renderCuts", {"ok": False, "error": "대본을 붙여넣으세요."}); return
        if not cfg.get("gemini_key"):
            self._js("renderCuts", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return
        n_cuts = (params or {}).get("nCuts") or "자동"
        # 낭독 속도 실측 8.7자/초(2026-08-08) × 사용자 배속 → 4~8초에 해당하는 글자 수
        cps = 8.7 * max(0.5, _fnum(cfg.get("typecast_tempo"), 1.0))
        # 자동 = **낭독 시간 기반**: 총 글자 ÷ (한 컷 5.5초 분량). 예전의 '문장 수 −2~+3'은
        # 짧은 문장 대본에서 프롬프트의 글자 기준(34~69자/컷)과 충돌해 2초 컷을 남발시키고,
        # 문단째 붙여넣으면 줄 수가 적게 잡혀 컷이 뭉텅이가 됐다 (2026-08-11 전환).
        # 목표치만 시간에서 나오고, 어느 문장이 어느 컷에 가는지(경계)는 계속 흐름 규칙이 정한다.
        n_chars = len(re.sub(r"\s", "", script))
        if n_cuts in ("자동", "", None):
            est = max(6, round(n_chars / (cps * 5.5)))
            n_txt = f"{max(est - 2, 6)}~{est + 3}"
        elif n_cuts == "촘촘":
            est = max(8, round(n_chars / (cps * 4.0)))   # 촘촘 = 4초 분량씩, 빠른 템포
            n_txt = f"{max(est - 1, 8)}~{est + 4}"
        else:
            n_txt = str(n_cuts)
        self._js("imgStatus", "컷 분해 중… (Gemini)")
        prompt = SCENE_SPLIT_PROMPT.format(n_cuts=n_txt, script=script[:12000],
                                           chars_lo=int(cps * 4), chars_hi=int(cps * 8))
        data = None
        # 실제로 쓴 모델과 토큰 — 끝나고 비용을 알려준다. Opus 가 실패해 Gemini 로 넘어가면
        # 둘 다 청구되므로 단가가 다른 둘을 따로 세서 더한다.
        kind, used = "gemini", {"opus": [0, 0], "gemini": [0, 0]}
        fallback_why = ""      # Opus 를 골랐는데 못 쓴 이유 — 결과 화면에 남긴다
        # 분해 모델 선택 — Opus 는 4모델 비교(2026-08-11)에서 캐논 준수·대사→화면 번역이 최고였다.
        # 대신 느리고(3~6분) 회당 ~250원이라 opt-in. 실패하면 Gemini 로 폴백해 분해가 끊기지 않는다.
        if (cfg.get("split_model") or "gemini") == "opus" and (cfg.get("anthropic_key") or "").strip():
            self._js("imgStatus", "컷 분해 중… (Claude Opus — 3~6분 걸릴 수 있습니다)")
            data, tin, tout = self._split_claude(cfg, prompt)
            used["opus"] = [tin, tout]
            if data:
                kind = "opus"
            else:
                why = getattr(self, "_split_claude_err", "") or "알 수 없는 이유"
                self._js("imgStatus", f"⚠ Claude Opus 분해 실패 — {why}. Gemini로 진행합니다")
                fallback_why = why
        if not data:
            try:
                from google import genai
                client = genai.Client(api_key=cfg["gemini_key"])
                for attempt in range(2):   # 파싱 실패 시 1회 재시도 (PRD 6-2)
                    resp = client.models.generate_content(model=GEMINI_MODEL, contents=[prompt])
                    um = getattr(resp, "usage_metadata", None)
                    if um:   # 재시도분도 실제로 청구되므로 누적한다
                        used["gemini"][0] += getattr(um, "prompt_token_count", 0) or 0
                        used["gemini"][1] += getattr(um, "candidates_token_count", 0) or 0
                    data = _parse_cuts(resp.text)
                    if data: break
            except Exception as e:
                self._js("renderCuts", {"ok": False, "error": str(e)[:200]}); return
        if not data:
            self._js("renderCuts", {"ok": False, "error": "컷 분해 결과를 해석하지 못했습니다. 다시 시도해 주세요."}); return
        self._finish_split(cfg, data, kind, used, fallback_why)

    def _finish_split(self, cfg, data, kind, used, fallback_why=""):
        """분해 결과를 화면으로 보낸다 — 정규화·강조 게이팅·컷 길이 배정이 전부 여기 있다.

        API 분해와 claude.ai 붙여넣기가 **같은 함수를 탄다**. 붙여넣기용으로 따로
        파싱하면 이 검사들을 통째로 건너뛰어, 같은 JSON 이 경로에 따라 다른 컷이 된다.
        (kind="paste" 면 토큰이 0 이라 비용 표시가 저절로 빠진다)"""
        # 상한을 넘어도 **자르지 않는다** — 조용히 버리면 대본 뒷부분이 통째로 사라진다.
        # (2026-08-10 제보: 33문장 대본이 20컷에서 잘려 절반이 증발)
        # 상한의 목적은 비용 방어인데, 그건 이미지 생성 단계에서 값을 보여주고 누르게 하는 걸로 충분하다.
        cuts, maxc = data.get("cuts") or [], _num(cfg.get("img_max_cuts"), 40)
        trimmed = max(0, len(cuts) - maxc)   # 자르지 않고 '경고용 개수'로만 쓴다
        # ② 컷별 길이 — 음성을 먼저 뽑아뒀으면 **실측 낭독 시간**으로 배정한다.
        # 안 뽑았으면 글자 수 추정으로 대신한다. 어느 쪽이든 영상 총길이가 음성에 맞는다.
        self._assign_cut_secs(cuts, cfg)
        default_ai = (cfg.get("img_default_mode") or "ai") == "ai"
        # 조용히 잘리거나 바뀐 값을 모은다 — 지금까지는 경고 없이 결과만 달라졌다
        # (실측: anno_label "Relieving Chamber"→"Relieving", measure_en "46년"→"46",
        #  style "tabletop"→snap). 값은 규칙대로 고치되 무엇이 바뀌었는지는 사람에게 알린다.
        trunc = []

        def _tr(no, field, was, now):
            """무엇이 바뀌었는지 사람에게 알린다.
            ⚠ 앞뒤를 똑같은 길이로 잘라 보내면 안 된다 — 길이 상한에 걸린 값은 앞부분이
            같아서 화면에 'A → A' 로 찍히고, 사용자는 왜 경고가 떴는지 알 수 없다
            (2026-08-16 실사고: compare_en 110자 컷이 그렇게 보였다).
            그래서 **길이와 잘려나간 뒷부분**을 따로 보낸다."""
            was, now = (was or "").strip(), (now or "")
            if not was or was == now:
                return
            # 순수 길이 컷인가 — 앞부분이 그대로면 뒤만 잘린 것이다
            tail = was[len(now):] if was.startswith(now) else ""
            trunc.append({"no": no, "field": field,
                          "was": was[:110], "now": now[:110],
                          "wlen": len(was), "nlen": len(now),
                          "cut": tail[:70]})

        for i, c in enumerate(cuts):
            c["no"] = i + 1
            c["type"] = (c.get("type") or "usage").strip()
            raw_style = (c.get("style") or "").strip()
            c["style"] = norm_style(raw_style)
            # 목록에 없는 톤을 지어내면 snap(폰카 스냅)으로 떨어진다 — 톤이 통째로 어긋난다
            if raw_style and raw_style not in STYLE_DEFAULTS and raw_style not in STYLE_MIGRATE:
                _tr(c["no"], "style", raw_style, c["style"])
            c["shot"] = c.get("shot") if c.get("shot") in SHOT_LINES else "close"
            # product 컷은 생성 안 함 — 실물 소스 필요 (PRD 6-1)
            c["motion"] = (c.get("motion_en") or "").strip()
            # 화면에 새길 수치 — 한글이 섞이면 AI가 뭉개므로 라틴/숫자만 남긴다
            raw_measure = (c.get("measure_en") or "")
            c["measure_en"] = re.sub(r"[^0-9A-Za-z.%°/-]", "", raw_measure)[:12]
            _tr(c["no"], "measure_en", raw_measure, c["measure_en"])
            raw_focus = (c.get("focus_en") or "").strip()
            c["focus_en"] = raw_focus[:140]
            _tr(c["no"], "focus_en", raw_focus, c["focus_en"])
            # 효과음 문구 — 소리는 **프롬프트 텍스트가 정한다**(공식 문서 2026-08-16).
            # 한글이 섞이면 그대로 나가 소리 지시가 깨지므로 라틴만 남긴다(measure_en 과 같은 이유).
            # 효과음을 끄면 쓰이지 않는다. 없어도 예전처럼 일반 문장으로 떨어진다(옛 JSON 호환).
            raw_snd = (c.get("sound_en") or "").strip()
            c["sound_en"] = re.sub(r"[^ -~]", "", raw_snd).strip()[:120]
            _tr(c["no"], "sound_en", raw_snd, c["sound_en"])
            # 캐릭터 시트 라벨 — anime 톤에서만 의미가 있다. 다른 톤에 남아 있으면
            # 시트를 안 쓰는 컷에 "character A" 지목이 새어들어간다
            c["chars"] = sheet_chars(c) if c["style"] == "anime" else []
            # 리빌·근거 — 아는 값만 통과 (모르는 값이 오면 프롬프트에 안 붙고 조용히 무시된다)
            rv = (c.get("reveal") or "").strip().lower()
            c["reveal"] = rv if rv in REVEAL_LINES else ""
            ev = (c.get("evidence") or "").strip().lower()
            c["evidence"] = ev if ev in EVIDENCE_LINES else ""
            # 리빌을 골랐으면 shot 은 화각만 남긴다 — 'cutaway' 가 남아 있으면 같은 지시가 두 번
            # 들어가 서로 다른 자름을 요구하게 된다 (SHOT_LINES 는 통째로 자르라고 말한다)
            if c["reveal"] and c.get("shot") == "cutaway":
                c["shot"] = "close"
            # 강조 종류·라벨 — 가리킬 대상이 없으면 둘 다 무의미하다
            k = (c.get("anno_kind") or "").strip().lower()
            k = ANNO_ALIAS.get(k, k)   # 옛 컷 JSON 의 hud → measure (버리지 않는다)
            c["anno_kind"] = k if (k in ANNO_KINDS and k != "manga" and c["focus_en"]) else ""
            raw_label = (c.get("anno_label") or "").strip()
            c["anno_label"] = anno_label(c) if c["focus_en"] else ""
            # 공백 포함 16자를 넘으면 첫 단어만 남는다 ("Relieving Chamber" → "Relieving")
            if raw_label and c["focus_en"] and len(raw_label) > 16:
                _tr(c["no"], "anno_label", raw_label, c["anno_label"])
            # 강조 장치는 컷당 하나 — 도구가 살아 있으면 motion 의 도형 애니메이션은 뺀다.
            # (도구가 없으면 그 절이 유일한 강조이므로 그대로 둔다 — 지침이 허용한 기능)
            # 2단 구조 그래픽 컷([4])은 도형이 이미 이미지에 구워져 있다 — motion 의 변화 절을
            # 걷어내면 도형이 정지한 채 남는다. 여기서는 살려두고, 겹치는 anno_kind 쪽을 아래에서 끈다
            c["motion"] = strip_graphic_motion(
                c["motion"], bool(c["anno_kind"]) and not is_graphic_cut(c))
            # 끝점 — 두 점을 잇는 도구에만 남긴다. 한 점을 가리키는 도구(reject·zone·glow)에
            # 붙으면 "여기서 저기까지"라는 지시가 X 표시나 영역선에 섞여 들어간다.
            # 한쪽만 온 것도 버린다 — 반쪽 끝점은 축을 못 정하면서 문장만 늘린다.
            fr = re.sub(r"[^\x20-\x7E]", "", (c.get("from_en") or "")).strip()[:90]
            to = re.sub(r"[^\x20-\x7E]", "", (c.get("to_en") or "")).strip()[:90]
            _tr(c["no"], "from_en", c.get("from_en"), fr)
            _tr(c["no"], "to_en", c.get("to_en"), to)
            if c["anno_kind"] not in ANNO_SPAN_KINDS or not (fr and to):
                fr = to = ""
            c["from_en"], c["to_en"] = fr, to
            # 흐르는 물질 — flow 컷에서만. 색이 여기서 갈린다
            f = (c.get("flow_of") or "").strip().lower()
            c["flow_of"] = f if (c["anno_kind"] == "flow" and f in FLOW_COLORS) else ""
            # 비교 대상 — scale(옆에 놓을 익숙한 물건) · versus(위 칸에 놓을 알려진 모습).
            # 없으면 두 도구 다 성립하지 않는다. versus 는 문장이 길어 넉넉히 받는다.
            raw_cmp = (c.get("compare_en") or "")
            cmp_en = re.sub(r"[^\x20-\x7E]", "", raw_cmp).strip()[:110]
            c["compare_en"] = cmp_en if c["anno_kind"] in ("scale", "versus") else ""
            if c["compare_en"]:
                _tr(c["no"], "compare_en", raw_cmp, cmp_en)
                # scale 은 프롬프트를 조립할 때 90자에서 한 번 더 잘린다 (versus 는 110자)
                if c["anno_kind"] == "scale" and len(cmp_en) > 90:
                    _tr(c["no"], "compare_en(scale 90자)", cmp_en, cmp_en[:90])
            # 홀로그램 재구성 컷 — 홀로그램 자체가 강조 장치라 주석이 겹치면 시안 두 벌이 된다.
            # 지시문([3-1])만으로는 재발한다(프롬프트-only 제한이 깨진 chain 폭주 전례와 동일 계열)
            # → 코드로 강제 공백. focus_en 이 비면 이미지·영상 주석 게이팅이 전부 무음으로 꺼진다.
            if is_holo_cut(c):
                c["focus_en"] = ""
                c["measure_en"] = ""
            # 분해뷰 컷 — 부품이 벌어진 배치 자체가 강조 장치다. 그 위에 HUD·화살표까지
            # 얹으면 무엇을 보라는 건지 갈린다 (홀로그램과 같은 이유로 코드에서 강제 공백)
            elif is_exploded_cut(c):
                c["focus_en"] = ""
                c["measure_en"] = ""
                c["anno_kind"] = ""
                c["anno_label"] = ""
            # 그래픽 컷([4]) — 이미지에 구운 도형이 그 컷의 강조 장치다. 지침 ③이 focus_en 을
            # 비우라고 하지만 지침만으로는 재발한다(홀로그램·분해뷰에서 겪은 계열) → 코드로 강제
            elif is_graphic_cut(c):
                c["focus_en"] = ""
                c["measure_en"] = ""
                c["anno_kind"] = ""
                c["anno_label"] = ""
            # 흐름 컷 — 굵은 띠가 이미 강조다. 수치·라벨은 띠 위에 겹쳐 읽기를 방해한다
            # (수치가 그 컷의 요점이면 분해기가 anno_kind=hud 로 잡게 되어 있다)
            elif c.get("anno_kind") == "flow":
                c["measure_en"] = ""
            BEATS = ("hook", "context", "constraint", "despair", "pivot", "solution", "analogy", "closing")
            c["beat"] = c.get("beat") if c.get("beat") in BEATS else ""
            # 분해기가 제안한 체인 — 1번 컷은 이을 수 없다
            c["chain"] = bool(c.get("chain")) and c["no"] > 1
        # 체인 검증 — LLM 이 "다 이어라"로 폭주하면 장면 전환이 사라진다 (실측 2026-08-06).
        # 고정 상한 대신 **대본이 실제로 같은 공간에 머무는지**로 판단한다:
        # 장소(place_en)나 피사체가 바뀌는 지점에서 끊고, 계속 머무르면 길게도 허용.
        def _key(c):
            return re.sub(r"[^a-z]", "", (c.get("place_en") or "").lower())[:22]

        def _subj_overlap(a, b):
            """영문 프롬프트의 명사 겹침 — 같은 대상을 계속 보고 있는지의 근거"""
            stop = {"the", "a", "an", "of", "in", "on", "at", "and", "with", "into", "from",
                    "over", "under", "its", "it", "is", "are", "to", "for", "by", "as", "that"}
            wa = {w for w in re.findall(r"[a-z]{4,}", (a.get("subject_en") or "").lower()) if w not in stop}
            wb = {w for w in re.findall(r"[a-z]{4,}", (b.get("subject_en") or "").lower()) if w not in stop}
            return len(wa & wb) >= 2

        for i, c in enumerate(cuts):
            if not c["chain"]:
                continue
            prev = cuts[i - 1]
            pa, pb = _key(prev), _key(c)
            same_place = bool(pa) and bool(pb) and (pa == pb or pa in pb or pb in pa)
            # 장소가 같거나(명시된 경우) 피사체 단어가 겹치면 '머무는 중' → 이어짐 유지
            if not (same_place or _subj_overlap(prev, c)):
                c["chain"] = False
        # 한 묶음이 5컷을 넘으면 끊는다 — 이유는 **화질이 아니라 리듬**이다.
        # (이미지 기준으로 바꾼 뒤로는 열화가 없다. 다만 한 공간에 20초 넘게 머물면
        #  쇼츠에서 지루해진다 — 실측: 실제 대본 20컷 중 최장 묶음이 4컷이라 여기 걸린 적은 없다)
        run = 0
        for c in cuts:
            if c["chain"]:
                run += 1
                if run > 4:
                    c["chain"] = False
                    run = 0
            else:
                run = 0
            # 실물(product)도 기본은 AI 생성 — '실물 권장' 배지만 달고, 전환은 사용자가 [🔍 실물로]
            c["mode"] = "ai" if default_ai else "off"
        anno_max = int(_num(cfg.get("anno_max_cuts"), 4))
        anno_off = cap_anno_cuts(cuts, anno_max)
        holo_n = sum(1 for c in cuts if is_holo_cut(c))   # 3컷 이상이면 검수 UI가 경고한다
        # 실제 청구 기준 비용 — 누르기 전엔 대본 길이만 알 뿐 출력 토큰을 모른다.
        # 그래서 시작 전 예상 대신 **끝난 뒤 실측**으로 알려준다.
        krw = sum(split_cost_krw(cfg, k, v[0], v[1]) for k, v in used.items())
        label = {"opus": "Claude Opus 5", "gemini": "Gemini",
                 "paste": "claude.ai (붙여넣기)"}.get(kind, kind)
        if kind == "gemini" and used["opus"][0]:
            label += " (Opus 실패 후 폴백 — 둘 다 청구됨)"
        elif kind == "gemini" and fallback_why:
            label += f" — Opus 를 골랐지만 못 썼습니다: {fallback_why}"
        cost = {"krw": krw, "model": label,
                "tin": sum(v[0] for v in used.values()),
                "tout": sum(v[1] for v in used.values())}
        self._js("renderCuts", {"ok": True, "title": data.get("title") or "제목없음",
                                "product_hint": data.get("product_hint") or "",
                                "cuts": cuts, "trimmed": trimmed, "holo": holo_n,
                                "annoOff": anno_off, "annoMax": anno_max,
                                "trunc": trunc[:12],
                                "reg_suggest": reg_suggest_from_cuts(cuts),
                                "cost": cost if (cost["tin"] or cost["tout"]) else None})

    # ── 자료 이미지 (소스 제작 탭) ──────────────────────────────────────
    # 이미지 생성 탭이 "대본 한 편을 컷으로 나눠 순서대로 만드는" 것이라면, 이쪽은
    # **대본에 없던 장면 한두 장**을 따로 만든다. 나눌 게 없으니 컷 분해가 통째로 빠지고,
    # 사용자가 한 줄 쓰면 그게 곧 subject_en 이다.
    # 프롬프트 조립·생성·비용은 기존 것을 그대로 쓴다 — 다른 길로 만들면 톤이 갈린다.
    def source_gen(self, params):
        threading.Thread(target=self._source_gen, args=(params,), daemon=True).start()
        return {"ok": True}

    def _source_gen(self, params):
        cfg = load_config()
        p = params or {}
        subj = (p.get("subject") or "").strip()
        if not subj:
            self._js("srcDone", {"ok": False, "error": "무엇을 만들지 한 줄 적어주세요."}); return
        if not cfg.get("gemini_key"):
            self._js("srcDone", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return
        n = max(1, min(4, _num(p.get("n"), 2)))
        raw_style = (p.get("style") or "collage").strip()
        mood = (p.get("mood") or "").strip().lower()
        aspect = p.get("aspect") or "16:9"
        model = p.get("model") or cfg.get("img_model") or "gemini-3.1-flash-image"
        size = p.get("size") or cfg.get("img_size") or "2K"
        outdir = source_outdir(cfg)
        # 톤 참고 — 이미지 생성 탭과 같은 칸을 쓴다. 넣어두면 색감·질감·조명을 따라간다
        # (피사체·구도는 따라하지 않는다 — STYLE_REF_LINE 이 그렇게 못박는다).
        refs = [r for r in (cfg.get("img_style_refs") or []) if os.path.exists(r)][:3]
        # 프롬프트 자유도 3단계:
        #   ① 톤 선택   — 팔레트가 96%를 채우고 사용자는 한 줄만 (기본)
        #   ② 직접 편집 — 조립 결과를 받아 고쳐서 그대로 보냄 (edited)
        #   ③ 톤 없음   — 조립을 아예 안 탄다 (style="none")
        # ②③ 을 둔 이유: 팔레트가 못 덮는 화면이 반드시 생기고, 그때 앱이 막아서면
        # 사용자는 앱 밖에서 만들게 된다. 다만 기본은 ① 이어야 한다 — 실측으로 다듬은
        # 네거티브·질감 규칙이 ②③ 에서는 통째로 빠지기 때문이다.
        edited = (p.get("prompt") or "").strip()
        if edited:
            prompt, style = edited, (raw_style if raw_style != "none" else "collage")
        elif raw_style == "none":
            prompt, style = subj, "collage"
        else:
            style = norm_style(raw_style)
            # 리빌 — 자료 한 장으로 단면·투시를 만들 수 있게 (컷 분해를 안 거치는 자리라
            # 사용자가 직접 고른다). 모르는 값이면 빈 문자열로 떨어져 조립에서 빠진다.
            rv = (p.get("reveal") or "").strip().lower()
            cut = {"no": 1, "style": style, "mood": mood, "shot": p.get("shot") or "object",
                   "reveal": rv if rv in REVEAL_LINES else "",
                   "beat": "context", "chars": [], "subject_en": subj,
                   "place_en": "", "weather_en": "", "motion": "", "camera": "",
                   "anno": "", "anno_kind": "", "focus_en": "", "measure_en": "",
                   "from_en": "", "to_en": "", "flow_of": "", "compare_en": "", "anno_label": ""}
            prompt = self._build_prompt(cfg, cut, refs, "")
        base = os.path.join(outdir, f"{style}_{_safe_name(subj[:24])}")
        self._js("srcStatus", f"생성 중… (0/{n})")
        done = 0
        for i in range(n):
            try:
                out = self._gen_image(cfg, prompt, refs, aspect, f"{base}_{i+1}", model, size, rot=i)
                done += 1
                self._js("srcImage", {"ok": True, "path": out, "no": i + 1,
                                      "file": os.path.basename(out), "prompt": prompt})
            except Exception as e:
                self._js("srcImage", {"ok": False, "no": i + 1, "error": self._img_err(str(e))})
            self._js("srcStatus", f"생성 중… ({i+1}/{n})")
        self._js("srcDone", {"ok": True, "n": done, "dir": outdir,
                             "krw": done * price_krw(cfg, model, size)})

    def pick_source_image(self):
        """영상으로 만들 이미지 한 장 고르기. 앱이 만든 것이 아니어도 된다 —
        캡컷에서 쓰던 것, 남에게 받은 것, 캡처한 것 무엇이든 I2V 로 넘긴다."""
        try:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                None, "영상으로 만들 이미지 선택", "",
                "이미지 (*.png *.jpg *.jpeg *.webp)")
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}
        if not path or not os.path.exists(path):
            return {"ok": False}
        return {"ok": True, "path": path}

    def source_preview(self, params):
        """[📄 프롬프트 보기] — 지금 설정으로 조립하면 무엇이 나가는지 그대로 돌려준다.
        생성 전에 눈으로 확인하고 고칠 수 있어야 왜 그렇게 나왔는지 추적할 수 있다."""
        cfg = load_config()
        p = params or {}
        subj = (p.get("subject") or "").strip()
        style = (p.get("style") or "collage").strip()
        if style == "none":
            return {"ok": True, "text": subj, "raw": True}
        refs = [r for r in (cfg.get("img_style_refs") or []) if os.path.exists(r)][:3]
        cut = {"no": 1, "style": norm_style(style), "mood": (p.get("mood") or "").strip().lower(),
               "shot": p.get("shot") or "object", "beat": "context", "chars": [],
               "subject_en": subj, "place_en": "", "weather_en": "", "motion": "", "camera": "",
               "anno": "", "anno_kind": "", "focus_en": "", "measure_en": "",
               "from_en": "", "to_en": "", "flow_of": "", "compare_en": "", "anno_label": ""}
        return {"ok": True, "text": self._build_prompt(cfg, cut, refs, ""), "raw": False}

    def source_vid_preview(self, params):
        """영상 프롬프트 초안. 톤에 맞는 움직임 한 줄 + 고정 규칙."""
        p = params or {}
        # 미리보기와 실제 생성이 같은 규칙을 타야 한다 — 'free'를 여기서 흘리면
        # 화면에는 고정 문구가 뜨는데 실제로는 잠금이 풀린 채로 나간다.
        cam0 = (p.get("camera") or "").strip()
        return {"ok": True, "text": source_video_prompt(p.get("style") or "collage",
                                                        cam0, free=(cam0 == "free")),
                "motion": SOURCE_MOTION.get(norm_style(p.get("style") or "collage"),
                                            SOURCE_MOTION_DEFAULT)}

    def source_vid(self, params):
        threading.Thread(target=self._source_vid, args=(params,), daemon=True).start()
        return {"ok": True}

    def _source_vid(self, params):
        """자료 이미지 한 장 → 영상 하나. 대본 컷의 영상 경로(_generate_videos_body)는
        컷 목록·체인·초 배정을 전제하므로 여기서는 생성 함수만 직접 부른다."""
        cfg = load_config()
        p = params or {}
        img = (p.get("path") or "").strip()
        if not os.path.exists(img):
            self._js("srcVidDone", {"ok": False, "error": "이미지를 찾지 못했습니다."}); return
        style = norm_style(p.get("style") or "collage")
        aspect = p.get("aspect") or "16:9"
        model = p.get("model") or cfg.get("vid_model") or "seedance-1-5-pro-251215"
        res = p.get("res") or cfg.get("vid_res") or "720p"
        eng0 = "seedance" if str(model).startswith(("seedance", "ep-")) else "veo"
        # 길이 — 엔진이 받는 값으로만 보낸다 (Seedance 2~12초 / Veo 4·6·8, 1080p·4k 는 8초 고정).
        # 예전엔 4·6·8 만 고를 수 있었다 — 자료 화면도 길게 쓸 일이 있어 엔진 한도까지 연다.
        secs = int(_num(p.get("secs"), 4))
        allow0 = SEEDANCE_SECONDS if eng0 == "seedance" else (VIDEO_SECS_BY_RES.get(res) or VIDEO_SECONDS)
        if secs not in allow0:
            secs = min(allow0, key=lambda a: abs(a - secs))
        # 카메라 — 기본은 '고정'이다. 자료 화면은 위에서 평평하게 내려다본 구도라 시점이 조금만
        # 틀어져도 가짜가 되고, 구조가 명확해서 요소 개수가 바뀌면 바로 티가 난다.
        # 다만 **사용자가 직접 고르면 그대로 따른다** — 프리셋을 고르면 그 워크가 프롬프트에
        # 들어가고 --camerafixed 를 붙이지 않는다 (프롬프트에 써도 안 먹던 유일한 항목이었다).
        # 세 상태다 (2026-08-15):
        #   ""     잠금 — 고정 문구 + --camerafixed
        #   free   워크는 지정하지 않고 잠금만 해제
        #   프리셋  그 워크가 프롬프트에 들어가고 잠금도 해제
        # 예전엔 앞의 둘이 한 칸이라 '워크는 안 정하고 잠금만 풀기'가 아예 불가능했다.
        cam = (p.get("camera") or "").strip()
        free = (cam == "free")
        if cam not in CAMERA_PRESETS:
            cam = ""    # 빈 값 = 고정 (free 도 워크 문구는 없다)
        # 소리 — sfx 만 실제로 오디오를 만든다(단가 2배). 나머지는 무음.
        audio = (p.get("audio") or "none").strip()
        # 영상도 이미지와 같은 3단계 — 안 쓰면 톤에 맞는 초안이 자동으로 붙고,
        # 쓰면 그게 그대로 나간다. 고정 규칙(카메라·글자 금지)은 초안에 이미 들어 있으므로
        # 사용자가 지우면 지워진 채로 간다 — 보이는 것이 나가는 것이라는 원칙.
        user_prompt = (p.get("prompt") or "").strip()
        prompt = user_prompt or source_video_prompt(style, cam, free=free)
        out = os.path.splitext(img)[0] + ".mp4"
        eng = next((m.get("engine") for m in VIDEO_MODELS if m.get("id") == model), "seedance")
        # 판수 — 컷 영상과 같은 방식. 판마다 다른 결과가 나오므로 미리 여러 판을 돌려두고
        # 나중에 고른다. 2판째부터 앞 판은 v1·v2… 로 보관된다(예전엔 그냥 덮어썼다).
        passes = max(1, min(5, int(_num(p.get("passes"), 1))))
        for pi in range(passes):
            self._js("srcStatus", (f"영상 생성 중… ({pi + 1}/{passes}판 · 1~3분)"
                                   if passes > 1 else "영상 생성 중… (1~3분)"))
            # 자료 소스도 판을 이름으로 쌓는다 (컷 영상과 같은 이유 — 캡컷이 문 파일 불변).
            # 여기는 컷 번호가 없어 파일명 자체로 다음 번호를 찾는다.
            _b, _e = os.path.splitext(out)
            _b = _VER_RE.sub("", _b)
            _n = 1
            while os.path.exists(f"{_b}_v{_n}{_e}"):
                _n += 1
            out = f"{_b}_v{_n}{_e}"
            moved = []
            try:
                if eng == "veo":
                    self._gen_veo(cfg, prompt, img, aspect, res, secs, out, model, no=0)
                else:
                    # camera_fixed — 잠금을 푸는 조건이 셋이다 (2026-08-15):
                    #   ① 워크를 골랐다 (cam)  ② '자유'를 골랐다 (free)
                    #   ③ 프롬프트를 직접 썼다 (user_prompt)
                    # ③이 중요하다 — 예전엔 사용자가 "camera slowly pans right" 라고 써도
                    # 셀렉트가 '고정'이면 --camerafixed 가 몰래 붙어 정면으로 싸웠다.
                    # 화면에 안 보이는 플래그가 결과를 바꾸면 안 된다.
                    #
                    # ⚠ 미니어처 예외(style != "tabletop")는 여기서 뺐다. 그게 박혀 있어서
                    #   사용자가 '고정'을 골라도 절대 고정되지 않았다 — 뒤집을 방법이 없었다.
                    #   기본값은 UI 가 '자유'로 잡아주므로 평소 동작은 그대로다.
                    self._gen_seedance(cfg, prompt, img, None, aspect, res, secs, out, model,
                                       no=0, audio=audio,
                                       camera_fixed=not (cam or free or user_prompt))
                self._js("srcVidDone", {"ok": True, "path": out, "pass": pi + 1, "passes": passes,
                                        "file": os.path.basename(out), "prompt": prompt})
            except Exception as e:
                for orig, arch in (moved or []):   # 실패했으니 보관해둔 이전 판을 제자리로
                    try:
                        os.replace(arch, orig)
                    except Exception:
                        pass
                self._js("srcVidDone", {"ok": False, "error": str(e)[:200]})
                return

    # ── ② 이미지 생성 ──
    def generate_images(self, params):
        # 플래그를 스레드 기동 '전에' 락과 함께 선점 — 검사~설정 사이 창으로 배치가 겹치지 않게
        with self._gen_lock:
            if self.img_running:
                return {"ok": False, "error": "이미 생성 중입니다."}
            self.img_running = True
        threading.Thread(target=self._generate_images, args=(params,), daemon=True).start()
        return {"ok": True}

    def _style_block(self, cfg, style):
        ov = cfg.get("img_style_override") or {}
        style = norm_style(style)
        return (ov.get(style) or STYLE_DEFAULTS[style]).strip()

    def _build_prompt(self, cfg, cut, refs, anno=""):
        """PRD 6-3 조립식 프롬프트. anno = '' | 'shape' | 'full' (홀로그램 계측 HUD 레이어)"""
        style = norm_style(cut.get("style"))
        shot = cut.get("shot") if cut.get("shot") in SHOT_LINES else "close"
        parts = ["SUBJECT: " + (cut.get("subject_en") or cut.get("scene_ko") or "").strip()]
        if (cut.get("place_en") or "").strip():
            parts.append(f"Setting: {cut['place_en'].strip()}.")
        # 날씨·대기 — 사실감 레이어. 같은 현장 컷들은 분해기가 같은 문구를 준다 (장면 일관성)
        if (cut.get("weather_en") or "").strip():
            parts.append(f"Atmosphere: {cut['weather_en'].strip()}")
        parts.append(f"Shot: {SHOT_LINES[shot]}")
        # 리빌 — '어떻게 열어 보이는가'. shot(화각)·style(화풍)과 독립된 축이라 따로 얹는다.
        rv = cut_reveal(cut)
        if rv:
            parts.append(REVEAL_LINES[rv])
        # 근거 수준 — 문화유산 복원 컷에서만. 확실한 것과 추정한 것을 그림으로 구분한다.
        ev = (cut.get("evidence") or "").strip().lower()
        if ev in EVIDENCE_LINES:
            parts.append(EVIDENCE_LINES[ev])
        parts.append(self._style_block(cfg, style))
        # 밝기 — 톤 바로 뒤에 얹는다. 앞에 두면 톤 문구가 덮어쓰고, 네거티브 뒤에 두면 묻힌다.
        mood = (cut.get("mood") or "").strip().lower()
        if mood in MOOD_LINES:
            parts.append(MOOD_LINES[mood])
        # 톤 프리셋이 피사체를 덮어쓰는 사고 방지 (2026-08-04 실측: arch3d가 모든 컷을 댐으로 만들었다)
        parts.append(SUBJECT_LOCK)
        # 주석 문구가 실제로 붙은 컷만 네거티브를 완화한다. 빈 문구인데 완화하면
        # "마크를 원한다"는 지시만 남아 맥락 없는 화살표가 흩뿌려진다 (2026-08-06 검증)
        blk = annotation_block(anno, cut, cfg.get("img_anno_color") or "auto") \
            if anno in ANNOTATION_MODES else ""
        if blk:
            parts.append(blk)
            base_neg = NEGATIVE_CORE_ANNO_FULL if '"' in blk else NEGATIVE_CORE_ANNO_SHAPE
        else:
            base_neg = NEGATIVE_CORE
        sneg = NEG_BY_STYLE.get(style, "")
        # 플랫 톤 + 강조 → 발광 금지와 발광 요구가 부딪힌다. 강조가 실제로 붙은 컷에서만 완화판.
        if blk and sneg is NEGATIVE_FLAT:
            sneg = NEGATIVE_FLAT_ANNO
        neg = base_neg + ("\n" + sneg if sneg else "")
        # 인물이 주인공인 톤 — 익명 실루엣 강제(FACE_HIDE)를 푼다. 안 풀면 얼굴이 안 나와
        # 인물 서사·작품 요약이 성립하지 않는다. 대신 각 톤의 복제 금지 잠금으로 갈아끼운다.
        if style in ("game", "story3d", "toy3d"):
            neg = neg.replace(FACE_HIDE, FACE_GAME)
        elif style in ("greycast", "whitecast"):
            neg = neg.replace(FACE_HIDE, FACE_MANNEQUIN)
        elif style == "anime":
            neg = neg.replace(FACE_HIDE, FACE_ANIME)
        parts.append(neg)
        if refs:
            # 📇 등록부가 고른 컷 — 대상별 개별 그림이 참조다 (시트·톤 레퍼런스보다 우선)
            _rd = cut.get("_reg_descs") or []
            if _rd:
                parts.append(REG_SHEET_LINE.format(n=len(_rd), descs="; ".join(_rd)))
                parts.append(REG_COUNT_LINE)
                return "\n\n".join(x for x in parts if x)
            # 참조 이미지의 쓰임은 셋 중 하나뿐이고 서로 지시가 정반대다 — 반드시 하나만 붙인다.
            #   캐릭터 시트: 인물을 그대로 / 피사체 시트: 사물을 그대로 / 톤 레퍼런스: 피사체는 복사 금지
            sheet = (cfg.get("char_sheet") or "").strip()
            subj = (cfg.get("subject_sheet") or "").strip()
            first = os.path.basename(refs[0])
            if style == "anime" and sheet and first == os.path.basename(sheet):
                parts.append(CHAR_SHEET_LINE)
                who = sheet_chars(cut)
                if who:
                    parts.append(CHAR_PICK_LINE.format(
                        who=" and ".join(f"character {w}" for w in who)))
            elif subj and first == os.path.basename(subj):
                parts.append(SUBJECT_SHEET_LINE)
            else:
                parts.append(STYLE_REF_LINE)
        return "\n\n".join(p for p in parts if p)

    # ── 컷별 낭독 길이 배정 ────────────────────────────────
    VID_ALLOWED = (4, 6, 8)          # Seedance/Veo 가 받는 길이

    def _assign_cut_secs(self, cuts, cfg):
        """각 컷의 대사가 몇 초인지 재서 cut["secs"] 에 넣는다.

        1순위: 방금 만든 음성의 단어 타임스탬프(실측) — 가장 정확하다.
        2순위: 글자 수 ÷ 낭독 속도(8.7자/초 × 배속) 추정.
        영상 모델은 4·6·8초만 받으므로 **모자라지 않게 올림**한다 —
        짧게 뽑으면 대사가 잘리지만, 길게 뽑으면 캡컷에서 자르면 그만이다.
        """
        if not cuts:
            return
        last = getattr(self, "_tc_last", None)
        words = (last or {}).get("words") or []
        cps = 8.7 * max(0.5, _fnum(cfg.get("typecast_tempo"), 1.0))
        wi, n = 0, len(words)
        for c in cuts:
            line = (c.get("line") or "").strip()
            need = len(self._PUNCT.sub("", line))
            secs = 0.0
            if words and need:
                got, st, en = 0, None, None
                while wi < n and got < need:
                    w = words[wi]
                    t = self._PUNCT.sub("", w.get("text") or "")
                    if not t:
                        wi += 1
                        continue
                    if st is None:
                        st = float(w["start"])
                    en = float(w["end"])
                    got += len(t)
                    wi += 1
                if st is not None and en is not None and en > st:
                    secs = en - st
                    c["measured"] = True
            if not secs and need:
                secs = need / cps          # 실측이 없으면 추정
            c["narr"] = round(secs, 2)
            # 모자라지 않게 **올림**. 여유(-0.15초 같은)를 주면 안 된다 —
            # 6.07초 대사에 6초 클립을 물리면 마지막 음절이 잘리고 복구가 안 된다.
            # 넘치는 건 캡컷에서 자르면 그만이다.
            c["secs"] = next((a for a in self.VID_ALLOWED if a >= secs), self.VID_ALLOWED[-1])
            # 8초를 넘는 대사는 한 클립으로 못 담는다 → 분해기가 더 잘게 쪼개야 한다는 신호
            c["over"] = secs > self.VID_ALLOWED[-1]

    def _img_workers(self, cfg, model):
        """이미지 동시 생성 수. 0(자동) = Seedream: 살아있는 무료 계정 수(최대 4) / Gemini: 2.
        Seedream 은 계정마다 API 제한·무료 쿼터가 따로라 계정 수만큼이 안전한 상한이고,
        Gemini 는 키가 하나라 동시 2까지만 — 그 이상은 429(rate limit) 위험이 실익을 넘는다."""
        n = int(_num(cfg.get("img_parallel"), 0))
        if n:
            return max(1, min(n, 6))
        if bp_is_image(model):
            try:
                lead = 0
                for kname, _k, is_free in self._seedance_keys(cfg, model):
                    if not is_free or kname.endswith("(소진)"):
                        break
                    lead += 1
                return max(1, min(lead, 4))
            except Exception:
                return 1
        return 2

    def _generate_images(self, params):
        try:
            self._generate_images_body(params)
        finally:
            self.img_running = False   # 어떤 경로로 끝나도(조기 return·예외 포함) 플래그 해제

    def _generate_images_body(self, params):
        cfg = load_config()
        p = params or {}
        cuts = [c for c in (p.get("cuts") or []) if c.get("mode") != "product"]
        if not cuts:
            self._js("imgDone", {"ok": False, "error": "생성할 컷이 없습니다."}); return
        if not cfg.get("gemini_key"):
            self._js("imgDone", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return

        is_test = bool(p.get("test"))
        # 판수 — 같은 배치를 N번 돌려 후보를 미리 쌓아둔다. 시드를 안 보내므로 매번 다른 그림이
        # 나오고, 2판째부터는 _archive_prev 가 앞 판을 v1·v2… 로 밀어준다(새 구조 불필요).
        # 한 판 뽑고 → 보고 → 다시 돌리는 왕복을 없애는 게 목적이라 톤 테스트에는 걸지 않는다.
        passes = 1 if is_test else max(1, min(5, int(_num(p.get("passes"), 1))))
        # 🧩 조립 강조 — 강조 컷을 CLEAN+INFO 두 장으로 (영상화 때 조립의 재료가 된다).
        # 톤 테스트에는 무의미하므로 끈다. 강조 컷당 이미지 비용이 2배가 된다.
        assemble = bool(p.get("assemble")) and not is_test
        anno = (p.get("anno") if p.get("anno") is not None else cfg.get("img_anno")) or ""
        model = p.get("model") or cfg.get("img_model") or "gemini-3.1-flash-image"
        size = p.get("size") or cfg.get("img_size") or "2K"
        aspect = p.get("aspect") or "9:16"
        refs = [r for r in (cfg.get("img_style_refs") or []) if os.path.exists(r)][:3]
        # 캐릭터 시트 — anime 톤 전용. 여러 컷에 같은 인물을 유지하는 유일한 수단이다.
        sheet = (cfg.get("char_sheet") or "").strip()
        if sheet and not os.path.exists(sheet):
            self._js("imgStatus", "⚠ 캐릭터 시트 파일을 찾지 못했습니다 — 인물이 컷마다 달라집니다")
            sheet = ""
        # 피사체 시트 — 톤 무관. 여러 컷에 같은 구조물·기계·유물을 유지한다 (캐논 문구의 그림판).
        subj_sheet = (cfg.get("subject_sheet") or "").strip()
        if subj_sheet and not os.path.exists(subj_sheet):
            self._js("imgStatus", "⚠ 피사체 시트 파일을 찾지 못했습니다 — 컷마다 생김새가 달라집니다")
            subj_sheet = ""

        # 재생성은 프론트가 원래 배치 폴더(outdir)를 넘겨준다.
        # 안 넘기면 folder 이름이 '오늘 날짜' 기준이라 자정을 넘겨 재생성할 때 딴 폴더로 흩어진다.
        outdir = (p.get("outdir") or "").strip()
        if not outdir:
            # 프로젝트 폴더 아래 '이미지/' 로 — 음성·자막·영상과 한자리에 모이되 종류별로 나뉜다
            outdir = project_dir(cfg, p.get("title") or "무제")
            outdir = os.path.join(outdir, "_톤테스트" if is_test else "이미지")
        elif not is_test:
            # 예전 드래프트는 배치 폴더가 프로젝트 루트다 — 정리된 프로젝트('이미지/' 존재)면 그리로
            sub = os.path.join(outdir, "이미지")
            if os.path.basename(outdir.rstrip("\\/")) != "이미지" and os.path.isdir(sub):
                outdir = sub
        try:
            os.makedirs(outdir, exist_ok=True)
        except Exception as e:
            self._js("imgDone", {"ok": False, "error": f"폴더 생성 실패: {str(e)[:120]}"}); return

        total, ok_n, spent, log = len(cuts), 0, 0, []
        # 🔎 배치 직전 잔량 실측 — 다른 컴퓨터가 쓴 사용량까지 반영해 소진 계정을 뺀다
        if bp_is_image(model):
            self._js("imgStatus", "🔎 무료 잔량 실측 중… (배치당 1회)")
            self._bp_sync_live("imgStatus")
            cfg = load_config()   # 스냅샷이 저장된 최신 설정으로
        # ── 병렬 생성 — 컷마다 출력 파일이 독립이라 갈라도 안전하다.
        # Seedream 은 계정 수만큼(계정별 쿼터·API 제한이 따로), Gemini 는 같은 키 동시 2요청.
        # 워커는 '생성'만 하고, 비용 합산·로그·UI 푸시는 이 스레드(수집부)에서만 한다 —
        # 사용량 기록(_track_bp_images)은 _CFG_LOCK 으로 이미 직렬화돼 있다.
        workers = max(1, min(self._img_workers(cfg, model), total))
        if workers > 1:
            self._js("imgStatus", f"⚡ {workers}장씩 동시 생성 ({total}컷)")

        def _one(idx, cut):
            no = cut.get("no") or (idx + 1)
            # ⏹ 중단 = 아직 시작 안 한 컷만 건너뛴다 (진행 중인 요청은 마무리)
            if not self.img_running:
                return {"no": no, "skipped": True}
            # 캐릭터 시트 — anime 컷에서만, 참조 이미지의 **맨 앞**에 둔다 (모델이 첫 장을
            # 가장 강하게 따른다). 톤 레퍼런스와 자리를 다투므로 합쳐서 3장 상한을 지킨다.
            cut_refs = refs
            # 📇 등록부 — 컷에 체크된 대상의 개별 그림만 참조 (시트보다 우선, 최대 3장).
            # 시트 통째 참조와 달리 "이 컷의 대상"만 넘어가므로 엉뚱한 대상 선택이 없다.
            cut.pop("_reg_descs", None)
            _reg = cfg.get("registry") or {}
            _sel = [str(l).strip() for l in (cut.get("reg") or []) if str(l).strip()]
            _rp, _rd = [], []
            for _l in _sel:
                _e = _reg.get(_l) or {}
                if _e.get("path") and os.path.exists(_e["path"]):
                    _rp.append(_e["path"])
                    _rd.append((_e.get("desc") or _l).strip().rstrip(" .;,"))
                if len(_rp) >= 3:
                    break
            if _rp:
                cut_refs = _rp
                cut["_reg_descs"] = _rd
            elif sheet and norm_style(cut.get("style")) == "anime":
                cut_refs = [sheet] + [r for r in refs if r != sheet][:2]
            elif subj_sheet:
                # 시트는 반드시 맨 앞 — 모델이 첫 장을 가장 강하게 따른다.
                # (캐릭터 시트와 동시에 쓰지 않는다: '인물 그대로'와 '사물 그대로'가 자리를 다툰다)
                cut_refs = [subj_sheet] + [r for r in refs if r != subj_sheet][:2]
            # 컷별 주석 설정이 있으면 우선, 없으면 배치 전역값(auto면 컷 성격에 따라 자동)
            # '자동'은 full 로 푼다 — 수치가 있는 컷에만 숫자가 얹히고 나머지는 도형만 나온다
            anno_mode = anno_for_cut(cut.get("anno") or anno, cut, "full")
            prompt = self._build_prompt(cfg, cut, cut_refs, anno_mode)
            # 🧩 조립용 강조 블록 — 실제로 강조가 붙는 컷에서만 (빈 블록이면 일반 컷과 동일)
            _ak = ANNO_ALIAS.get((cut.get("anno_kind") or "").strip().lower(),
                                 (cut.get("anno_kind") or "").strip().lower())
            asm_blk = annotation_block(anno_mode, cut, cfg.get("img_anno_color") or "auto")                 if (assemble and anno_mode in ANNOTATION_MODES and _ak not in ASSEMBLE_SKIP) else ""
            tag = f"_{cut.get('style')}" if is_test else ""
            out_base = os.path.join(outdir, f"{no:02d}{tag}_{_safe_name(cut.get('scene_ko'))}")
            moved = _archive_prev(outdir, no) if not is_test else []   # 이전 결과물은 _ver01 로 개명 보관
            try:
                if asm_blk:
                    # ① CLEAN — 같은 장면, 강조만 없음. '조립전/' 하위 폴더에 둔다:
                    #   본 폴더에 NN_ 접두로 두면 _resolve_start_frame 이 이걸 시작 프레임으로
                    #   잘못 집는다 (NN_ 첫 매칭 규칙).
                    cdir = os.path.join(outdir, "조립전")
                    os.makedirs(cdir, exist_ok=True)
                    p_clean = self._build_prompt(cfg, cut, cut_refs, "")
                    clean_out = self._gen_image(cfg, p_clean, cut_refs, aspect,
                                                os.path.join(cdir, f"{no:02d}"), model, size, rot=idx)
                    # ② INFO — CLEAN 을 참조로 강조만 얹는 편집 (장면 보존 · 2026-08-18 실측 검증)
                    prompt = INFO_EDIT_HEAD + asm_blk + INFO_EDIT_TAIL
                    out = self._gen_image(cfg, prompt, [clean_out], aspect, out_base, model, size, rot=idx)
                    return {"no": no, "ok": True, "file": os.path.basename(out), "path": out,
                            "style": cut.get("style"), "prompt": prompt, "assembled": True}
                out = self._gen_image(cfg, prompt, cut_refs, aspect, out_base, model, size, rot=idx)
                return {"no": no, "ok": True, "file": os.path.basename(out), "path": out,
                        "style": cut.get("style"), "prompt": prompt}
            except Exception as e:
                # 재생성 실패 시 아카이브한 이전 이미지를 원위치 — 없으면 영상이 조용히 T2V로 격하된다
                for orig, arch in (moved or []):
                    try:
                        os.replace(arch, orig)
                    except Exception:
                        pass
                return {"no": no, "ok": False, "error": self._img_err(str(e)),
                        "style": cut.get("style"), "prompt": prompt}

        from concurrent.futures import ThreadPoolExecutor, as_completed
        done_all = 0            # 전 판 합계 — 끝나고 성공/실패를 셀 때 쓴다
        for pi in range(passes):
            if not self.img_running:      # ⏹ 는 판 경계에서도 확인 — 돌린 데까지 남기고 끝낸다
                break
            if passes > 1:
                self._js("imgStatus", f"▶ {pi + 1}판째 / {passes}판 — 앞 판은 v 폴더로 보관됩니다")
            done_n = 0
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = [ex.submit(_one, i, c) for i, c in enumerate(cuts)]
                for fu in as_completed(futs):
                    r = fu.result()
                    if r.get("skipped"):
                        continue
                    done_n += 1
                    done_all += 1
                    if r.get("ok"):
                        ok_n += 1
                        spent += price_krw(cfg, model, size)   # 실패 컷은 가산하지 않음 (PRD 7.3)
                        if r.get("assembled"):
                            spent += price_krw(cfg, model, size)   # 🧩 CLEAN+INFO 두 장
                        log.append(r)
                        self._js("renderImage", dict(r, model=model, test=is_test))
                    else:
                        log.append(r)
                        self._js("renderImage", dict(r, test=is_test))
                    if self.img_running:
                        head = f"[{pi + 1}/{passes}판] " if passes > 1 else ""
                        self._js("imgStatus", f"{head}({done_n}/{total}) 완료 — #{r.get('no')}")
        if not self.img_running:
            self._js("imgStatus", "⏹ 중단됨")
        total = done_all or total     # 판수를 곱한 실제 시도 수 (imgDone 의 실패 계산용)

        # 사용액 누적 — 배치 종료 시 1회만 기록 (PRD 7.4)
        if spent:
            with _CFG_LOCK:   # 설정 저장·사용량 기록과의 덮어쓰기 경합 방지
                cfg2 = load_config()
                sp = dict(cfg2.get("img_spent") or {})
                mk = datetime.now().strftime("%Y-%m")
                sp[mk] = _num(sp.get(mk), 0) + spent
                cfg2["img_spent"] = sp
                save_config(cfg2)
        # 프롬프트 전문 저장 (재현·재생성용) + 합성 고지문구 (PRD 7.2 / 8)
        # 재생성은 컷 1개짜리 배치로 들어오므로, 통째로 덮어쓰면 나머지 컷 기록이 날아간다 → no 기준 병합.
        if not is_test:
            try:
                pjson = os.path.join(outdir, "_프롬프트.json")
                prev = []
                if os.path.exists(pjson):
                    try:
                        prev = (json.load(open(pjson, encoding="utf-8")) or {}).get("results") or []
                    except Exception:
                        prev = []
                merged = {r.get("no"): r for r in prev}
                merged.update({r.get("no"): r for r in log})
                json.dump({"title": p.get("title") or "", "model": model, "size": size,
                           "aspect": aspect, "refs": refs,
                           "results": [merged[k] for k in sorted(merged, key=lambda x: (x is None, x))]},
                          open(pjson, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                open(os.path.join(outdir, "_고지문구.txt"), "w", encoding="utf-8").write(NOTICE_TXT)
            except Exception:
                pass
        self._js("imgDone", {"ok": True, "total": total, "success": ok_n,
                             "fail": total - ok_n, "spent": spent, "dir": outdir, "test": is_test})

    def regenerate_image(self, params):
        """단일 컷 재생성 — 모델 승급 가능. generate_images를 컷 1개로 재사용."""
        p = dict(params or {})
        p["cuts"] = [p.get("cut") or {}]
        return self.generate_images(p)

    # ── ③ 영상 생성 (Veo 3.1) ──
    def get_video_price_table(self):
        """초당 과금이라 프론트가 초×단가를 실시간 계산해야 한다."""
        cfg = load_config()
        # 계정에 등록된 접근 지점(ep-…)을 모델 목록에 얹는다 — 보상 캠페인용
        eps = []
        for a in self._bp_accounts(cfg):
            if a["ep"]:
                eps.append({"id": a["ep"], "label": f"🎁 {a['name']}",
                            "note": "보상 캠페인 · " + a["ep"][:14], "engine": "seedance"})
        for ln in (cfg.get("byteplus_eps") or "").splitlines():   # 구버전 호환
            ln = ln.strip()
            if not ln:
                continue
            eid, _, label = ln.partition("|")
            eid = eid.strip()
            if eid and not any(e["id"] == eid for e in eps):
                eps.append({"id": eid, "label": (label.strip() or "내 접근 지점"),
                            "note": "보상 캠페인 대상 · " + eid[:14], "engine": "seedance"})
        return {"ok": True, "models": VIDEO_MODELS + eps, "seconds": VIDEO_SECONDS,
                "secs_by_res": VIDEO_SECS_BY_RES, "resolutions": VIDEO_RES,
                "tempos": [{"id": "dynamic", "label": "역동적 (쇼츠 기본)"},
                           {"id": "hyper", "label": "배속·타임랩스 느낌"},
                           {"id": "calm", "label": "차분한 설명형"}],
                "motions": [{"group": g, "id": k, "label": ko, "en": en}
                            for g, items in MOTION_PRESETS for k, ko, en in items],
                # 'room' 은 시댄스에서 generate_audio=false → **완전 무음**이다.
                # 베오는 오디오를 끌 수 없어(Always on) 문구로만 조용하게 시킨다.
                # 그래서 라벨은 '무음'이 사실에 가깝다 — 예전 '조용한 룸톤(나레이션용)'은
                # 소리가 나는 줄 오해하게 만들었다 (2026-08-16).
                "audios": [{"id": "room", "label": "무음 (권장)"},
                           {"id": "sfx", "label": "장면 효과음 (물소리 등 · 대사/음악 없음)"}],
                "cameras": [{"id": k, "label": CAMERA_LABELS[k], "group": g,
                             "desc": CAMERA_DESCS.get(k, "")}
                            for g, ks in CAMERA_GROUPS for k in ks],
                "prices": [{"model": m, "res": r,
                            "usd": u * seedance_audio_mult(cfg, m),
                            "krw_per_sec": round(u * seedance_audio_mult(cfg, m)
                                                 * _num(cfg.get("usd_krw"), 1460))}
                           for (m, r), u in VIDEO_PRICE_USD.items()]
                          # 접근 지점은 기준 모델 단가를 그대로 물려준다 (비용 표시·해상도 목록용)
                          + [{"model": e["id"], "res": r,
                              "usd": VIDEO_PRICE_USD.get((cfg.get("byteplus_ep_base") or
                                                          "seedance-1-5-pro-251215", r), 0),
                              "krw_per_sec": round(VIDEO_PRICE_USD.get(
                                  (cfg.get("byteplus_ep_base") or "seedance-1-5-pro-251215", r), 0)
                                  * _num(cfg.get("usd_krw"), 1460))}
                             for e in eps for r in ("480p", "720p", "1080p")],
                "secs_by_model": dict(
                    {m["id"]: SEEDANCE_SECONDS for m in VIDEO_MODELS if m.get("engine") == "seedance"},
                    **{e["id"]: SEEDANCE_SECONDS for e in eps}),
                "spent": (cfg.get("vid_spent") or {}),
                "month": datetime.now().strftime("%Y-%m")}

    def video_stop(self):
        self.vid_running = False
        return {"ok": True}

    def generate_videos(self, params):
        # 이미지와 동일 — 플래그를 스레드 기동 전에 락과 함께 선점
        with self._gen_lock:
            if getattr(self, "vid_running", False):
                return {"ok": False, "error": "이미 영상 생성 중입니다."}
            self.vid_running = True
        threading.Thread(target=self._generate_videos, args=(params,), daemon=True).start()
        return {"ok": True}

    @staticmethod
    def _auto_camera(cut):
        """장면에 맞는 카메라 워크. 훅(1번)은 무조건 다가가기로 시선을 잡는다.
        좌우 이동은 컷 번호 홀짝으로 교대시켜 연속 컷이 같은 방향으로 몰리지 않게 한다.

        **강조가 붙은 컷은 조용한 카메라만 쓴다.** 치수선·화살표는 구조에 고정돼 있어서
        카메라가 계속 밀고 들어가면 화면 밖으로 밀려난다 — 문구로는 못 막는다
        (2026-08-12 실측: 6초 클립에서 화살표가 3초 만에 프레임을 벗어나 사라졌다).
        레퍼런스도 계측 그래픽이 있는 컷은 카메라가 거의 고정이었다."""
        no = cut.get("no") or 0
        # 분할 비교는 카메라가 아예 못 움직인다. 화면을 가른 레이아웃이라 시점이 조금만
        # 바뀌어도 두 면이 같은 장면이라는 전제가 깨진다 — 느린 밀기조차 안 된다.
        if (cut.get("anno_kind") or "").strip().lower() == "versus":
            return "still"
        # 자료 화면 계열 톤도 마찬가지다. 실사 장면은 카메라가 움직여 새 영역이 드러나도 모델이
        # 그럴듯하게 채우지만(나무가 몇 그루든 아무도 모른다), 자료 화면은 구조가 명확해서
        # 하나만 달라져도 바로 티가 난다 (실측 2026-08-13: 미니어처 설원 컷에서 스키어가
        # 5명→2명→7명이 되고 없던 안개가 생겼다).
        st = norm_style(cut.get("style"))
        if st in SOURCE_STYLES:
            # 미니어처(tabletop)만 예외 — 시차가 있어야 '작은 모형'으로 읽힌다. 완전히 고정하면
            # 그냥 그림이 된다. 다만 강조 컷에서 검증된 slowpush 여야 개수가 유지된다.
            return "slowpush" if st == "tabletop" else "still"
        quiet = bool((cut.get("anno_kind") or "").strip()) or bool((cut.get("focus_en") or "").strip())
        if quiet:
            # 훅이라도 강조가 있으면 조용한 쪽으로 — 시선이 그래픽에 머물러야 한다
            return "slowpush" if (cut.get("shot") in ("wide", "pov")) else "still"
        # game 톤의 넓은 컷은 3인칭 팔로우가 기본 — 게임다움의 절반은 이 카메라다
        if norm_style(cut.get("style")) == "game" and cut.get("shot") in ("wide", "pov"):
            return "gamecam"
        cam = CAMERA_AUTO_BEAT.get(cut.get("beat")) or             CAMERA_AUTO_SHOT.get(cut.get("shot")) or             CAMERA_AUTO_TYPE.get(cut.get("type")) or "push"
        if cam in ("panright", "panleft"):
            cam = "panright" if no % 2 else "panleft"
        return cam

    @staticmethod
    def _ffmpeg_exe():
        """프로젝트 다운로더 폴더의 ffmpeg 우선, 없으면 imageio_ffmpeg 폴백."""
        p = os.path.join(APP_DIR, "다운로더", "ffmpeg.exe")
        if os.path.exists(p):
            return p
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None

    @classmethod
    def _extract_last_frame(cls, video_path, out_png):
        """클립의 끝 프레임 추출 — 체이닝의 시작 프레임이 된다.
        맨 끝(-0.1s)은 모션블러가 잦아서 끝에서 0.4초 앞을 먼저 시도한다."""
        import subprocess
        ff = cls._ffmpeg_exe()
        if not ff or not os.path.exists(video_path):
            return None
        for sseof in ("-0.4", "-1.0"):
            try:
                subprocess.run([ff, "-y", "-sseof", sseof, "-i", video_path,
                                "-frames:v", "1", "-q:v", "2", out_png],
                               capture_output=True, timeout=60, creationflags=0x08000000)
            except Exception:
                return None
            if os.path.exists(out_png) and os.path.getsize(out_png) > 1000:
                return out_png
        return None

    @classmethod
    def _make_preview(cls, video_path):
        """앱 내 재생용 미리보기(WebM/VP8) 변환 — QtWebEngine 기본 빌드에는 H.264 디코더가
        없어 원본 mp4 를 <video> 로 못 튼다(회색 박스). 로열티프리 VP8 은 디코딩되므로
        480p 저용량으로 변환해 컷 카드에서 바로 확인하게 한다.
        실패해도 생성 흐름은 막지 않는다 — 그땐 [▶ 재생](시스템 플레이어)만 쓰면 된다."""
        import subprocess
        try:
            ff = cls._ffmpeg_exe()
            if not ff or not os.path.exists(video_path):
                return ""
            pdir = os.path.join(os.path.dirname(video_path), "_미리보기")
            os.makedirs(pdir, exist_ok=True)
            outp = os.path.join(pdir, os.path.splitext(os.path.basename(video_path))[0] + ".webm")
            # realtime/cpu-used 8 = 화질보다 속도 — 미리보기 용도라 4~8초 클립이 수 초면 끝난다
            r = subprocess.run([ff, "-y", "-i", video_path,
                                "-vf", "scale=-2:480", "-c:v", "libvpx", "-b:v", "600k",
                                "-deadline", "realtime", "-cpu-used", "8",
                                "-c:a", "libvorbis", "-b:a", "64k", outp],
                               capture_output=True, timeout=120, creationflags=0x08000000)
            return outp if r.returncode == 0 and os.path.exists(outp) and os.path.getsize(outp) > 1000 else ""
        except Exception:
            return ""

    @staticmethod
    def _resolve_prev_clip(vid_dir, no):
        """⛓ 체인용 — 바로 앞 번호부터 내려가며 가장 가까운 완성 클립을 찾는다.
        (앞 컷이 product 라 영상이 없을 수 있으므로 no-1 고정이 아니라 하향 탐색)"""
        for prev in range(no - 1, 0, -1):
            # 판이 여럿이면 **최신 판**을 잇는다 — 컷 카드가 보여주는 것과 같은 판이어야
            # 사용자가 놀라지 않는다 (2026-08-19 판 파일명 전환)
            p = vid_latest(vid_dir, prev)
            if p:
                return p
        return None

    @staticmethod
    def _resolve_start_frame(image_path, out_path, no):
        """시작 프레임 경로 확정 — 프론트가 못 넘겼으면 배치 폴더에서 컷 번호로 찾는다."""
        if image_path and os.path.exists(image_path):
            return image_path
        if not no:
            return None
        root = os.path.dirname(os.path.dirname(out_path))   # <프로젝트>/영상/x.mp4 → <프로젝트>
        # 새 구조는 이미지가 '이미지/' 하위, 구버전 프로젝트는 루트에 바로 있다 — 순서대로 찾는다
        for imgdir in (os.path.join(root, "이미지"), root):
            try:
                for fn in sorted(os.listdir(imgdir)):
                    if fn.startswith(f"{no:02d}_") and fn.lower().endswith((".jpg", ".png", ".webp")):
                        return os.path.join(imgdir, fn)
            except Exception:
                continue
        return None

    def _build_motion_prompt(self, cfg, cut, has_image=False, tempo="dynamic", audio="room",
                             vanno="", vcolor="auto", has_last=False, cam_state=None):
        """시작 프레임 유무로 프롬프트를 가른다 (공식 I2V 지침).
        이미지가 있으면 장면·스타일을 다시 쓰지 않는다 — 이미지가 이미 그걸 정의했고,
        다시 묘사하면 이미지와 싸워서 장면이 어긋난다. 카메라·모션·오디오만 지시한다."""
        cam = CAMERA_MIGRATE.get(cut.get("camera"), cut.get("camera"))
        if cam in (None, "", "auto") or cam not in CAMERA_PRESETS:
            cam = self._auto_camera(cut)
            if cut.get("chain"):
                # 레퍼런스 훅 롱테이크 공식: 하강(1번 컷) → 활강 → 상승·공전 → 후퇴
                seq = ["push", "riseorbit", "pullup", "orbit"]
                pos = max(1, int(cut.get("_chain_pos") or 1))
                cam = seq[min(pos - 1, len(seq) - 1)]
                # 같은 워크가 연달아 나오면 방향을 꺾는다 — '직전 컷'은 묶음 상태(cam_state)가
                # 있으면 그걸 본다 (병렬 생성에서 다른 묶음의 카메라와 섞이면 안 된다)
                _prev_cam = (cam_state.get("last_cam") if cam_state is not None
                             else getattr(self, "_last_cam", None))
                if cam == _prev_cam:
                    cam = CHAIN_TURN.get(cam, "orbit")
        # 강조가 붙은 컷은 격한 워크를 쓰지 않는다 — 분해기가 직접 지정했든 체인 공식이
        # 골랐든 여기서 걸러낸다. 치수선·화살표는 구조에 고정돼 있어 카메라가 밀고 들어가면
        # 프레임 밖으로 밀려나고, 그러면 강조가 있으나 마나가 된다 (2026-08-12 실측).
        if cam in CAMERA_LOUD and ((cut.get("anno_kind") or "").strip()
                                   or (cut.get("focus_en") or "").strip()):
            cam = "slowpush" if cut.get("shot") in ("wide", "pov") else "still"
        if cam_state is not None:
            cam_state["last_cam"] = cam
        else:
            self._last_cam = cam
        # 기본값이 '은은한 움직임'이면 쇼츠에선 배경화면이 된다 — 비어 있으면 크고 분명한 변화 하나를 요구
        motion = (cut.get("motion") or "").strip() or \
            "one clear, dramatic visual change unfolds — the most eye-catching thing this scene could naturally do"
        # 주석 애니메이션은 Motion 에 이어 붙인다 — 카메라·템포와 싸우지 않게
        aline = video_anno_line(vanno, cut, vcolor)
        if aline:
            motion = motion + "\n" + aline
        # 강조가 붙은 컷은 템포도 차분하게. 카메라를 slowpush 로 묶어놓고 템포가
        # "빠른 리프레임과 핸드헬드 에너지를 환영한다"고 하면 두 지시가 정면으로 싸운다
        # (2026-08-12 발견 — 카메라 게이트를 넣고 최종 프롬프트를 읽다 잡았다).
        quiet = bool((cut.get("anno_kind") or "").strip() or (cut.get("focus_en") or "").strip())
        if quiet:
            tempo = "calm"
        # 도착 프레임이 걸린 컷도 마찬가지 — dynamic 템포의 "빠른 리프레임·속도 변화"가
        # 이음매를 흔들어 다음 클립과 안 맞는다 (Flow 자문 2026-08-12).
        elif has_last:
            tempo = "smooth"
        tempo_line = VIDEO_TEMPO.get(tempo) or VIDEO_TEMPO["dynamic"]
        audio_line = VIDEO_AUDIO_MODES.get(audio) or VIDEO_AUDIO_MODES["room"]
        # 효과음 컷 — 분해기가 써준 소리가 있으면 일반 문장 대신 그걸 쓴다.
        # 금지문(대사·음악)은 반드시 유지한다: 이 모델은 립싱크·다국어 대사가 주력이라
        # 막지 않으면 사람 목소리가 섞인다(공식 문서 2026-08-16). 나레이션을 따로 얹는 우리에겐 치명적.
        if audio == "sfx":
            # 조립 시점에서도 한 번 더 거른다 — _finish_split 을 안 거치는 경로(재생성·부분 배치)가
            # 한글을 그대로 흘려보내면 소리 지시가 깨진다 (measure_en 과 같은 이중 방어)
            snd = re.sub(r"[^ -~]", "", (cut.get("sound_en") or "")).strip()[:120]
            if snd:
                audio_line = ("Sound design: " + snd.rstrip(" .;,") + ". Clearly audible and "
                              "synced to the motion, and nothing else is heard. "
                              "No dialogue, no speech, no voice-over, no music, no crowd chatter.")
        # 시작 이미지에 수치(HUD readout)가 구워져 있으면 지키게 한다 (2026-08-10 전환).
        # 새 글자 생성은 계속 금지 — 이미지에 이미 있는 readout 만 선명하게 유지시킨다.
        neg = VIDEO_NEGATIVE
        # 수치와 영문 라벨은 둘 다 2K 이미지에만 굽는다 — 영상은 '유지'만 시킨다.
        # (라벨을 영상에서 새로 그리게 하면 720p 에서 뭉개진다 — 수치와 같은 실패 계열)
        imode = anno_for_cut(cut.get("anno") or (cfg.get("img_anno") or ""), cut, "full")
        m = (cut.get("measure_en") or "").strip()[:12]
        if imode != "full":
            m = ""
        lb = anno_label(cut) if imode == "full" else ""
        keep = " / ".join(f'"{x}"' for x in (m, lb) if x)
        if has_image and keep:
            motion += "\n" + VIDEO_TEXT_KEEP.format(m=keep)
            # 주석 템플릿 끝의 전면 텍스트 금지를 '그 글자 제외'로 좁힌다 (모순 방지).
            # 화살표·X·영역 판은 그 문장이 문장 첫머리라 대문자다 — 둘 다 잡아야 한다
            # (소문자만 치환하면 금지문이 남아 모델이 이미지의 라벨을 지운다)
            for pat in ("no letters, digits or words.", "No letters, digits or words."):
                motion = motion.replace(pat, pat[:-1] + " beyond that existing text.")
            neg = VIDEO_NEGATIVE_KEEP
        # 홀로그램 컷 — 시작 이미지에 구워진 홀로그램을 지키게 한다 (VIDEO_TEXT_KEEP 과 대칭).
        # 홀로 컷은 focus_en 이 강제 공백이라 주석 줄(aline)과 겹칠 일이 없다.
        if has_image and is_holo_cut(cut):
            motion += "\n" + VIDEO_HOLO_KEEP
        # game 톤 — 룩의 절반은 '움직임의 질량'이다. 물리 무게감 절을 항상 요구하고,
        # I2V 는 시작 이미지의 게임 렌더 룩이 실사로 드리프트하지 않게 잠근다
        cstyle = norm_style(cut.get("style"))
        if cstyle == "game":
            motion += "\n" + VIDEO_GAME_PHYS
            if has_image:
                motion += "\n" + VIDEO_GAME_LOOK
        # 나머지 인물 3D 톤 — 물리 무게감은 같이 필요하고, 룩 잠금만 톤에 맞게 갈아끼운다.
        # 마네킹 계열은 '얼굴이 생기는 것'까지 막아야 한다 (얼굴 없음이 정체성)
        elif cstyle in ("story3d", "toy3d"):
            motion += "\n" + VIDEO_GAME_PHYS
            if has_image:
                motion += "\n" + VIDEO_TONE_LOOK
        elif cstyle in ("greycast", "whitecast"):
            motion += "\n" + VIDEO_GAME_PHYS
            if has_image:
                motion += "\n" + VIDEO_CAST_LOOK
        # 만화 요약 톤 — 물리 무게감은 필요 없고(플랫 그림이다) 룩 잠금만 건다
        elif cstyle == "anime" and has_image:
            motion += "\n" + VIDEO_ANIME_LOOK
        # 속을 연 컷 — 이미지에서 이미 갈라져 있다. 영상이 껍질을 휘거나 녹여 '다시 여는'
        # 것을 막는다. 리빌 방식 전체(부분절개·국부파냄·고스트…)와 xsection 톤을 같이 잡는다.
        #
        # **단 사용자가 잠금을 끄면**(영상 바의 [단면 잠금] = 끔) 여는 것을 허용한다 —
        # "겉면이 걷히며 속이 보이는" 연출을 한 컷 안에서 시도하려면 이 잠금이 걸림돌이다.
        # 대신 완전 방임은 아니다: 없던 내부 구조를 지어내는 것만은 계속 막는다(대표 실패).
        if has_image and is_cut_open(cut):
            if cut.get("_xlock") is False:
                motion += "\n" + VIDEO_XSECTION_OPEN
                neg += VIDEO_XSECTION_OPEN_NEG
            else:
                motion += "\n" + VIDEO_XSECTION_LOCK
                neg += VIDEO_XSECTION_NEGATIVE
        # 분해뷰 — 부품은 이미 벌어져 있다. 직선 이동 한 번만 (회전·산개가 대표 실패)
        if has_image and is_exploded_cut(cut):
            motion += "\n" + VIDEO_EXPLODED_KEEP
            neg += VIDEO_EXPLODED_NEGATIVE
        # 도착 프레임이 걸린 체인 컷 — 두 프레임이 같은 공간이면 '실제 이동으로 도착',
        # 다른 공간이면 '매개를 통과해 전환'. 후자에 전자를 쓰면 걸어갈 수 없는 거리를
        # 시키는 셈이라 모델이 크로스페이드·모핑으로 때운다 (우리가 금지한 실패다).
        if has_image and has_last:
            motion += "\n" + (VIDEO_LAST_FRAME_ARRIVE if cut.get("_same_place")
                              else VIDEO_LAST_FRAME_BRIDGE)
        if has_image:
            return MOTION_PROMPT_I2V.format(
                camera=CAMERA_PRESETS[cam], motion=motion, tempo=tempo_line,
                drive=(VIDEO_DRIVE_HOLD if quiet else VIDEO_DRIVE_CHANGE),
                audio=audio_line, negative=neg)
        shot = cut.get("shot")
        shot_line = f"Shot: {SHOT_LINES[shot]}\n" if shot in SHOT_LINES else ""
        scene = (cut.get("subject_en") or cut.get("scene_ko") or "").strip()
        # T2V(이미지 없음)일 때만 — I2V는 이미지에 이미 대기가 구워져 있다
        if (cut.get("weather_en") or "").strip():
            scene += f" Atmosphere: {cut['weather_en'].strip()}."
        return MOTION_PROMPT.format(
            shot_line=shot_line,
            scene=scene,
            camera=CAMERA_PRESETS[cam], motion=motion,
            style=self._style_block(cfg, norm_style(cut.get("style"))),
            tempo=tempo_line, audio=audio_line, negative=neg)

    def _generate_videos(self, params):
        try:
            self._generate_videos_body(params)
        finally:
            self.vid_running = False   # 어떤 경로로 끝나도 플래그 해제

    def _generate_videos_body(self, params):
        cfg = load_config()
        p = params or {}
        cuts = [c for c in (p.get("cuts") or []) if c.get("mode") != "product"]
        # ⛓ 체인은 앞 클립이 먼저 완성돼 있어야 하므로 컷 번호 순서를 보장한다
        cuts.sort(key=lambda c: _num(c.get("no"), 999))
        if not cuts:
            self._js("vidDone", {"ok": False, "error": "영상으로 만들 컷이 없습니다."}); return
        if not cfg.get("gemini_key"):
            self._js("vidDone", {"ok": False, "error": "설정에 Gemini 키가 필요합니다."}); return

        model = p.get("model") or "veo-3.1-lite-generate-preview"
        res = p.get("res") or "720p"
        # ep-… 는 BytePlus 접근 지점(엔드포인트) — 이름으로 모델을 알 수 없고, 데이터 협업
        # 보상도 이걸로 호출해야 카운트된다. 허용 길이가 Veo(4/6/8)와 Seedance(2~12초)로
        # 달라서 클램프보다 **먼저** 엔진을 정한다 — 전에는 Veo 목록으로만 걸러서
        # Seedance 의 5·10·12초가 조용히 4초로 떨어졌다 (2026-08-13).
        engine = "seedance" if str(model).startswith(("seedance", "ep-")) else "veo"
        # 판수 — 같은 배치를 N번 돌려 후보를 쌓아둔다 (이미지와 같은 방식).
        # 2판째부터 _archive_prev 가 앞 판을 v1·v2… 로 밀어준다. 영상은 컷당 1~3분이라
        # 판수를 올리면 시간이 곱으로 늘어난다 — '자는 동안 돌려놓기'가 이 기능의 목적이다.
        passes = max(1, min(5, int(_num(p.get("passes"), 1))))
        # 단면 잠금 — 기본 켬(지금까지의 동작). 끄면 리빌·xsection 컷에서 영상이 겉을 열 수 있다.
        # 720p 가 절단면 뒤를 새로 그리면 뭉개지므로 기본값은 바꾸지 않는다 — 시도용 스위치다.
        xlock = str(p.get("xlock", "1")) not in ("0", "false", "False", "")
        secs = _num(p.get("secs"), 4)
        if engine == "seedance":
            if secs not in SEEDANCE_SECONDS:
                secs = min(SEEDANCE_SECONDS, key=lambda a: abs(a - secs))
        elif secs not in VIDEO_SECONDS:
            # 4 로 떨어뜨리면 10초를 고른 사용자가 8초가 아니라 4초를 받는다 — 가까운 값으로
            secs = min(VIDEO_SECONDS, key=lambda a: abs(a - secs))
        aspect = p.get("aspect") or "9:16"
        tempo = p.get("tempo") or cfg.get("vid_tempo") or "dynamic"
        audio = p.get("audio") or cfg.get("vid_audio") or "room"
        vanno = (p.get("vanno") if p.get("vanno") is not None else cfg.get("vid_anno")) or ""
        # 시작 이미지에 HUD가 이미 그려져 있으면 'draw'(새로 켜라)는 이중으로 그리라는 말이 된다.
        # 이미지를 어떤 주석 설정으로 뽑았는지를 보고 animate(살리기)/draw(새로) 를 자동으로 고른다.
        img_anno = (p.get("img_anno") if p.get("img_anno") is not None
                    else cfg.get("img_anno")) or ""
        if (model, res) not in VIDEO_PRICE_USD:
            self._js("vidDone", {"ok": False,
                                 "error": f"{model} 는 {res} 를 지원하지 않습니다."}); return
        # ⚠ 해상도 제한은 **Veo 전용**이다. 여기서 엔진을 안 보면 바로 위에서 지킨 Seedance 의
        # 5·10·12초가 다시 4초로 떨어진다 — 2026-08-13 수정이 반쪽이라 재발했다 (2026-08-14 실측:
        # 10초를 골라도 4초 클립이 나왔다). Seedance 는 해상도와 무관하게 2~12초를 받는다.
        allowed = SEEDANCE_SECONDS if engine == "seedance" else (VIDEO_SECS_BY_RES.get(res) or VIDEO_SECONDS)
        if secs not in allowed:
            # allowed[0] 로 떨어뜨리면 8초를 고른 사용자가 4초를 받는다 → 가장 가까운 값으로
            secs = min(allowed, key=lambda a: abs(a - secs))

        outdir = (p.get("outdir") or "").strip()
        if not outdir:
            outdir = project_dir(cfg, p.get("title") or "무제")
        # 프론트가 넘기는 outdir 는 이미지 배치 폴더다 — '이미지/' 면 프로젝트 루트로 올라가
        # '영상/' 을 나란히 만든다. 구버전 프로젝트(_영상/ 이 이미 있는 곳)는 그대로 이어 쓴다.
        if os.path.basename(outdir.rstrip("\\/")) == "이미지":
            outdir = os.path.dirname(outdir.rstrip("\\/"))
        _old_vdir = os.path.join(outdir, "_영상")
        outdir = _old_vdir if os.path.isdir(_old_vdir) else os.path.join(outdir, "영상")
        try:
            os.makedirs(outdir, exist_ok=True)
        except Exception as e:
            self._js("vidDone", {"ok": False, "error": f"폴더 생성 실패: {str(e)[:120]}"}); return

        total, ok_n, spent, log = len(cuts), 0, 0, []
        done_all = 0          # 판수를 곱한 **실제 시도 수** — 실패 계산의 분모다.
        # 이게 없으면 2판에서 total(=컷 수 17)보다 ok_n(=34)이 커져 실패가 -17로 찍힌다
        # (이미지 쪽은 이미 보정돼 있는데 영상만 빠져 있었다 — 2026-08-15 사용자 제보).
        # 🔎 배치 직전 잔량 실측 — 다른 컴퓨터가 쓴 사용량까지 반영해 소진 계정을 뺀다
        if engine == "seedance":
            self._js("vidStatus", "🔎 무료 잔량 실측 중… (배치당 1회)")
            self._bp_sync_live("vidStatus")
            cfg = load_config()   # 스냅샷이 저장된 최신 설정으로
        # ── 병렬 생성 (2026-08-19, 할 일 #4·#5) ────────────────────────────
        # 체인이 이미지 기준(2026-08-10)이라 컷 간 '파일' 의존이 없다 — 병렬의 근거.
        # 그래도 순차로 묶는 것: ① 연속 체인 구간(카메라 시퀀스·HUD 이어받기가 앞 컷
        # 상태를 본다) ② from_prev 컷(앞 클립 파일 필요). 그래서 병렬 단위는 컷이 아니라
        # **묶음(연속 체인 구간)**이고, 묶음 안은 기존 그대로 순차다.
        # 계정당 동시 1 원칙: 워커 = Seedance 계정 수(최대 4), 묶음마다 키 시작점을
        # 돌려(key_offset) 같은 계정에 몰리지 않게 한다 — 무료 쿼터 동시 소비·계정별
        # 서버 큐 정체 방지 (2026-08-19 씬2 실측 교훈). Veo 는 키 하나라 순차 유지.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        segs = []
        for _i, _c in enumerate(cuts):
            if _i > 0 and (_c.get("chain") or _c.get("from_prev")) and segs:
                segs[-1].append(_i)
            else:
                segs.append([_i])
        if engine == "seedance" and len(segs) > 1:
            _n = int(_num(cfg.get("vid_parallel"), 0))
            if not _n:
                try:
                    _n = len(self._seedance_keys(cfg, model))
                except Exception:
                    _n = 1
            workers = max(1, min(_n, 4, len(segs)))
        else:
            workers = 1
        if workers > 1:
            self._js("vidStatus", f"⚡ {workers}개 묶음 동시 생성 ({len(segs)}묶음 · 계정당 1개)")
        _lock = threading.Lock()
        _prog = {"try": 0}

        for _pass in range(passes):
            if not self.vid_running:      # ⏹ 는 판 경계에서도 확인 — 돌린 데까지 남기고 끝낸다
                break
            if passes > 1:
                self._js("vidStatus", f"▶ {_pass + 1}판째 / {passes}판 — 앞 판은 v 폴더로 보관됩니다")
            _ptag = f" · {_pass + 1}/{passes}판" if passes > 1 else ""

            def _one_cut(i, cut, st, seg_i):
                """컷 하나 생성 — 예전 순차 본문 그대로, 판 공유 변수만 묶음 상태(st)로 바꿨다.
                st = {"last_cam", "prev_anno", "chain_pos"} — 묶음 안에서만 이어달린다."""
                with _lock:
                    _prog["try"] += 1
                    _t = _prog["try"]
                # 프론트가 계산한 대본상 절대 위치가 있으면 우선 — 부분 배치에서도 같은 카메라가 나오게
                fp = int(_num(cut.get("chain_pos"), 0))
                st["chain_pos"] = fp if fp else (st["chain_pos"] + 1 if cut.get("chain") else 0)
                cut["_chain_pos"] = st["chain_pos"]
                cut["_xlock"] = xlock      # 단면 잠금 — 끄면 한 컷 안에서 '겉이 걷히는' 것을 허용
                no = cut.get("no") or (i + 1)
                # 컷별 길이 오버라이드 — 엔진 허용값에 가장 가까운 값으로 보정
                csecs = int(_num(cut.get("secs"), 0)) or secs
                allow = SEEDANCE_SECONDS if engine == "seedance" else (VIDEO_SECS_BY_RES.get(res) or VIDEO_SECONDS)
                if csecs not in allow:
                    csecs = min(allow, key=lambda a: abs(a - csecs))
                self._js("vidStatus", f"({_t}/{total * passes}) #{no} 영상 생성 중… ({csecs}초 · 1~3분 소요){_ptag}")
                # 판을 이름으로 쌓는다 — 기존 파일은 손대지 않는다 (캡컷이 문 소재 불변).
                # 실패해도 되돌릴 것이 없다: 새 파일이 안 만들어질 뿐이다.
                out = vid_next_path(outdir, no, _safe_name(cut.get('scene_ko')))
                vmoved = []
                start = self._resolve_start_frame(cut.get("image"), out, no)
                # ⛓ '앞 클립 끝에서 시작' (컷별 opt-in) — 같은 묶음에서 앞 컷이 먼저 끝나 있다
                if cut.get("chain") and cut.get("from_prev"):
                    vdir = os.path.dirname(out)
                    pclip = self._resolve_prev_clip(vdir, int(_num(no, 0)))
                    fr = pclip and self._extract_last_frame(
                        pclip, os.path.join(vdir, f"{int(_num(no, 0)):02d}_chain_.png"))
                    if fr:
                        start = fr   # "_chain_" 파일명 → chained_from_prev(HUD 중복 방지)가 인식
                        self._js("vidStatus", f"#{no} ⛓ 앞 클립({os.path.basename(pclip)}) 끝 프레임에서 시작합니다")
                    else:
                        self._js("vidStatus", f"#{no} ⚠ 앞 클립이 없어 '앞 클립에서 시작'을 못 씁니다 — "
                                              f"이미지/텍스트 기준으로 진행 (앞 컷 영상을 먼저 만들어 주세요)")
                elif cut.get("chain") and start:
                    self._js("vidStatus", f"#{no} ⛓ 이 컷 이미지에서 시작합니다")

                # 도착 프레임 = 다음 컷의 이미지 (2026-08-10 개편 그대로)
                last = None
                nxt = cuts[i + 1] if i + 1 < len(cuts) else None
                if nxt and nxt.get("from_prev"):
                    nxt = None
                if nxt and nxt.get("chain") and int(_num(nxt.get("no"), 0)) == int(_num(no, 0)) + 1:
                    nxt_img = self._resolve_start_frame(nxt.get("image"), out, int(_num(nxt.get("no"), 0)))
                    if nxt_img and (not start or os.path.abspath(nxt_img) != os.path.abspath(start)):
                        last = nxt_img
                        cut["_same_place"] = same_place(cut, nxt)
                        self._js("vidStatus", f"#{no} ⛓ 다음 컷(#{nxt.get('no')}) 이미지로 "
                                 + ("도착하게" if cut["_same_place"] else "통과 전환으로") + " 생성")
                elif cut.get("next_chain") and not cut.get("next_from_prev"):
                    # 부분 재생성 — 다음 체인 컷이 배치에 없어도 도착 프레임은 걸어야 이음매가 산다
                    nn = int(_num(no, 0)) + 1
                    nxt_img = self._resolve_start_frame((cut.get("next_image") or "").strip(), out, nn)
                    if nxt_img and (not start or os.path.abspath(nxt_img) != os.path.abspath(start)):
                        last = nxt_img
                        self._js("vidStatus", f"#{no} ⛓ 다음 컷(#{nn}) 이미지로 도착하게 생성 — 배치 밖 체인 유지")
                    else:
                        self._js("vidStatus", f"#{no} ⚠ 다음 컷(#{nn}) 이미지를 못 찾아 도착 지정 없이 생성합니다"
                                              f" — #{nn}와의 이음매가 어긋날 수 있어요")
                if cut.get("from_prev") and not last:
                    own = self._resolve_start_frame(cut.get("image"), out, no)
                    if own and (not start or os.path.abspath(own) != os.path.abspath(start)):
                        last = own
                        self._js("vidStatus", f"#{no} ⛓ 이 컷 이미지로 '도착'하게 생성합니다")
                if not start and cut.get("image"):
                    self._js("vidStatus", f"#{no} ⚠ 시작 이미지를 찾지 못해 텍스트 기반으로 생성합니다")
                chained_from_prev = bool(cut.get("chain")) and start and "_chain_" in os.path.basename(start)
                # 🧩 조립 강조 — CLEAN 짝이 있으면 시작=CLEAN → 도착=INFO
                akind = ANNO_ALIAS.get((cut.get("anno_kind") or "").strip().lower(),
                                       (cut.get("anno_kind") or "").strip().lower())
                asm_clean = ""
                if start and akind and akind not in ASSEMBLE_SKIP and not chained_from_prev:
                    _cl = os.path.join(os.path.dirname(start), "조립전", f"{int(_num(no, 0)):02d}.jpg")
                    if os.path.exists(_cl):
                        asm_clean = _cl
                if asm_clean and engine != "seedance" and int(csecs) != 8:
                    self._js("vidStatus", f"#{no} ⚠ Veo 조립(보간)은 8초 전용 — 이 컷은 조립 없이 생성합니다")
                    asm_clean = ""
                if asm_clean:
                    accent = anno_accent(cfg.get("img_anno_color") or "auto", cut)
                    last = start                      # 도착 = 강조가 구워진 INFO
                    start = asm_clean                 # 시작 = CLEAN
                    prompt = VIDEO_ASSEMBLE_TMPL.format(
                        accent=accent,
                        stages=ASSEMBLE_STAGES.get(akind, ASSEMBLE_STAGE_DEFAULT),
                        audio_line=VIDEO_AUDIO_MODES.get(audio) or VIDEO_AUDIO_MODES["room"])
                    st["last_cam"] = "slowpush"       # --camerafixed 가 붙지 않게 (느린 밀기 유지)
                    st["prev_anno"] = True            # 이 컷이 그래픽을 만들었다 (체인 이어받기 판단용)
                    self._js("vidStatus", f"#{no} 🧩 조립 강조 — CLEAN 에서 시작해 {akind} 가 조립되며 착지합니다")
                else:
                    kind = "animate" if (chained_from_prev and st["prev_anno"]) \
                        else _video_anno_kind(img_anno, cut, bool(start))
                    vmode = anno_for_cut(cut.get("vanno") or vanno, cut, kind)
                    st["prev_anno"] = bool(video_anno_line(vmode, cut, cfg.get("img_anno_color") or "auto"))
                    prompt = self._build_motion_prompt(
                        cfg, cut, has_image=bool(start), tempo=tempo, audio=audio,
                        vanno=vmode, vcolor=cfg.get("img_anno_color") or "auto",
                        has_last=bool(last), cam_state=st)
                try:
                    if engine == "seedance":
                        # 카메라가 '고정'이면 전용 플래그로 확실히 잠근다. key_offset 은 계정 분산.
                        self._gen_seedance(cfg, prompt, start, last, aspect, res, csecs, out, model, no,
                                           audio=audio, camera_fixed=(st.get("last_cam") == "still"),
                                           key_offset=seg_i)
                    else:
                        self._gen_veo(cfg, prompt, start, aspect, res, csecs, out, model, no,
                                      last_path=last)
                    pv = self._make_preview(out)
                    self._js("renderVideo", {"no": no, "ok": True, "path": out,
                                             "file": os.path.basename(out), "secs": csecs,
                                             "model": model, "prompt": prompt, "preview": pv})
                    return {"no": no, "ok": True, "file": os.path.basename(out), "path": out,
                            "secs": csecs, "prompt": prompt, "preview": pv,
                            "_spent": video_price_krw(cfg, model, res, csecs, audio=audio)}
                except Exception as e:
                    # 실패로 남은 반쪽 파일은 지운다 — 안 지우면 '최신 판'으로 잡힌다
                    try:
                        if os.path.exists(out) and os.path.getsize(out) < 20000:
                            os.remove(out)
                    except Exception:
                        pass
                    msg = self._img_err(str(e))
                    self._js("renderVideo", {"no": no, "ok": False, "error": msg, "prompt": prompt})
                    return {"no": no, "ok": False, "error": msg, "prompt": prompt, "_spent": 0}

            def _run_seg(seg_i, idxs):
                """묶음 하나 — 안은 순차 (카메라 시퀀스·prev_anno·from_prev 의존 보존)."""
                st = {"last_cam": None, "prev_anno": False, "chain_pos": 0}
                got = []
                for i in idxs:
                    if not self.vid_running:
                        self._js("vidStatus", "⏹ 중단됨")
                        break
                    got.append(_one_cut(i, cuts[i], st, seg_i))
                return got

            if workers <= 1:
                results = []
                for _si, _idxs in enumerate(segs):
                    if not self.vid_running:
                        break
                    results.extend(_run_seg(_si, _idxs))
            else:
                results = []
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futs = [ex.submit(_run_seg, _si, _idxs) for _si, _idxs in enumerate(segs)]
                    for fu in as_completed(futs):
                        try:
                            results.extend(fu.result() or [])
                        except Exception as _e:
                            self._js("vidStatus", f"⚠ 묶음 실패: {str(_e)[:120]}")
            for r in sorted(results, key=lambda x: _num(x.get("no"), 999)):
                done_all += 1
                sp1 = r.pop("_spent", 0)
                if r.get("ok"):
                    ok_n += 1
                    spent += sp1
                log.append(r)
        self.vid_running = False

        if spent:
            with _CFG_LOCK:   # 설정 저장·사용량 기록과의 덮어쓰기 경합 방지
                c2 = load_config()
                sp = dict(c2.get("vid_spent") or {})
                mk = datetime.now().strftime("%Y-%m")
                sp[mk] = _num(sp.get(mk), 0) + spent
                c2["vid_spent"] = sp
                save_config(c2)
        try:
            pj = os.path.join(outdir, "_영상프롬프트.json")
            prev = []
            if os.path.exists(pj):
                try: prev = (json.load(open(pj, encoding="utf-8")) or {}).get("results") or []
                except Exception: prev = []
            merged = {r.get("no"): r for r in prev}
            merged.update({r.get("no"): r for r in log})
            json.dump({"title": p.get("title") or "", "model": model, "res": res, "secs": secs,
                       "results": [merged[k] for k in sorted(merged, key=lambda x: (x is None, x))]},
                      open(pj, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass
        total = done_all or total     # 판수를 곱한 실제 시도 수 (vidDone 의 실패 계산용)
        self._js("vidDone", {"ok": True, "total": total, "success": ok_n,
                             "fail": max(0, total - ok_n), "spent": spent, "dir": outdir,
                             "passes": passes})

    @staticmethod
    def _bp_accounts(cfg):
        """계정 목록 — [{key, ep, name, ak, sk}]. 한 줄에 하나:

            ark-키 | ep-접근지점 | 이름 | ak=AKLT… | sk=…

        ep·이름·ak·sk 는 생략 가능하고 **순서도 상관없다** (접두사로 구분한다).
        계정마다 무료 쿼터가 따로라 잔량 조회도 계정별 AK/SK 로 해야 한다.
        ak/sk 를 안 적으면 설정의 공용 AK/SK 를 쓴다.
        """
        out, seen = [], set()
        raw = (cfg.get("byteplus_accounts") or "")
        # 구버전 필드 호환 — 무료 키 목록만 있던 시절
        raw += "\n" + (cfg.get("byteplus_free_keys") or "") + "\n" + (cfg.get("byteplus_key_free") or "")
        g_ak = (cfg.get("byteplus_ak") or "").strip()
        g_sk = (cfg.get("byteplus_sk") or "").strip()
        for ln in raw.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parts = [p.strip() for p in ln.split("|")]
            key = next((p for p in parts if p.startswith("ark-")), "")
            if not key or key in seen:
                continue
            seen.add(key)
            ep = next((p for p in parts if p.startswith("ep-")), "")
            ak = next((p[3:].strip() for p in parts if p.lower().startswith("ak=")), "")
            sk = next((p[3:].strip() for p in parts if p.lower().startswith("sk=")), "")
            name = next((p for p in parts
                         if p and not p.startswith(("ark-", "ep-"))
                         and not p.lower().startswith(("ak=", "sk="))), "")
            out.append({"key": key, "ep": ep, "name": name or f"계정{len(out)+1}",
                        "ak": ak or g_ak, "sk": sk or g_sk})
        return out

    def _track_bp_images(self, key, kname, model, n=1):
        """Seedream 은 '장당' 과금이고 영상 토큰과 **쿼터가 완전히 별개**다.
        같은 통에 넣으면 이미지 몇 장에 영상 계정이 소진 판정된다 → 모델별 장수로 따로 센다."""
        try:
            with _CFG_LOCK:   # 병렬 생성 시 읽기-수정-쓰기 레이스로 카운트가 유실되지 않게
                cfg2 = load_config()
                used = dict(cfg2.get("byteplus_img_used") or {})
                kid = f"{key[-10:]}|{model}"
                used[kid] = int(_num(used.get(kid), 0)) + n
                cfg2["byteplus_img_used"] = used
                save_config(cfg2)
            q = int(_num((cfg2.get("byteplus_img_quota") or {}).get(model), SEEDREAM_QUOTA.get(model, 150)))
            rem = max(0, q - used[kid])
            self._js("imgStatus", f"🎁 {kname} · {model.split('-')[0]} 무료 잔여 추정 {rem}장")
        except Exception:
            pass

    @classmethod
    def _seedance_keys(cls, cfg, model="", skip_spent=True):
        """이 호출에 쓸 키를 순서대로. 접근 지점(ep-)이 지정되면 그 계정 키를 맨 앞에 둔다 —
        ep 는 계정 전용이라 다른 키로 부르면 반드시 실패하기 때문.

        ⚠ BytePlus 는 무료 쿼터가 바닥나도 에러를 내지 않고 그 계정에 그대로 과금한다.
        실패를 기다리면 전환이 영영 안 일어나므로, 누적 토큰이 쿼터를 넘긴 계정은 **미리 건너뛴다**.
        (건너뛴 계정도 맨 뒤에 남겨둔다 — 추정이 틀렸을 때의 안전망)"""
        keys, spent_out = [], []
        if (cfg.get("byteplus_prefer") or "free") == "free":
            accs = cls._bp_accounts(cfg)
            if str(model).startswith("ep-"):
                owner = next((a for a in accs if a["ep"] == model), None)
                if owner:
                    accs = [owner] + [a for a in accs if a is not owner]
            # 이미지(Seedream)는 '장' 쿼터, 영상(Seedance)은 '토큰' 쿼터 — 통이 다르므로 따로 센다
            is_img = bp_is_image(model)
            if is_img:
                iu = cfg.get("byteplus_img_used") or {}
                quota = int(_num((cfg.get("byteplus_img_quota") or {}).get(model),
                                 SEEDREAM_QUOTA.get(model, 150)))
                def _spent(a):
                    return int(_num(iu.get(f"{a['key'][-10:]}|{model}"), 0))
            else:
                # 영상 토큰은 **매일 리셋된다** — 보상이 '전날 사용량만큼(일 상한)' 다음 날
                # 다시 들어오므로, 봐야 하는 건 누적이 아니라 **오늘 얼마 썼나**다.
                #
                # 예전엔 누적(byteplus_used)으로 정렬·소진 판정을 했다. 그러면
                #   ① 누적이 적은 계정 하나만 계속 쓰이고 (오늘 이미 썼어도 여전히 1순위)
                #   ② 누적이 상한을 넘긴 계정은 오늘 한 토큰도 안 썼는데 영구 제외된다.
                # 실측 2026-08-13: 5계정 중 1개만 쓰이고 1개는 영구 제외 — 하루 보상 한도
                # 2,500만 중 500만만 받고 있었다.
                today = datetime.now().strftime("%Y-%m-%d")
                day = (cfg.get("byteplus_daily") or {}).get(today) or {}
                quota = int(_num(cfg.get("byteplus_daily_cap"),
                                 _num(cfg.get("byteplus_free_quota"), 5_000_000)))
                def _spent(a):
                    return int(_num(day.get(a["key"][-10:]), 0))
            # 분산 모드: 덜 쓴 계정부터 — 보상이 '계정별 전날 사용량' 기준이라 골고루 써야 매일 다 받는다.
            # (ep 지정 시엔 그 계정이 1순위여야 하므로 재정렬하지 않는다)
            if (cfg.get("byteplus_rotate") or "spread") == "spread" and not str(model).startswith("ep-"):
                accs = sorted(accs, key=_spent)
            # 실측 스냅샷 — 배치 시작 때 _bp_sync_live 가 갱신한 '잔량 0' 계정 (5분 유효).
            # 로컬 추정이 낙관적으로 틀렸을 때(다른 컴퓨터가 쓴 사용량)의 마지막 방어선.
            _live = (cfg.get("byteplus_live") or {})
            _empty = (_live.get("empty") or {}).get("img" if is_img else "vid") or {} \
                if time.time() - _num(_live.get("ts"), 0) < 1800 else {}
            for a in accs:
                spent = _spent(a)
                if skip_spent and _empty.get(a["key"][-6:]):
                    spent_out.append((a["name"] + "(소진)", a["key"], True))
                elif skip_spent and quota and spent >= quota:
                    spent_out.append((a["name"] + "(소진)", a["key"], True))
                else:
                    keys.append((a["name"], a["key"], True))
        # '중단' 모드에서는 유료·소진 계정을 뒤에 붙이지 않는다 → 남은 무료가 없으면 빈 목록 = 생성 중단
        if (cfg.get("byteplus_prefer") or "free") == "free" and \
           (cfg.get("byteplus_on_empty") or "paid") == "stop":
            return keys
        paid = (cfg.get("byteplus_key") or "").strip()
        if paid and paid not in [k for _, k, _ in keys]:
            keys.append(("유료", paid, False))
        return keys + spent_out

    def _track_bp_tokens(self, key, kname, is_free, tokens, no=0):
        """사용 토큰을 **날짜별로** 쌓는다.

        데이터 협업 보상은 '전날 사용량만큼(일 상한 500만)' 다음 날 다시 들어온다.
        그래서 실제로 봐야 하는 건 총 잔여가 아니라 **오늘 얼마 썼나**다 —
        오늘 상한 안에서 쓰면 내일 그만큼 채워지고, 넘긴 만큼은 안 돌아온다.
        BytePlus 는 잔여 조회 API 가 없어(2026-08-10 전 경로 확인) 로컬 집계가 유일한 수단이다.
        """
        try:
            with _CFG_LOCK:   # 설정 저장과 겹치면 방금 저장된 키를 옛 스냅샷으로 덮어쓴다
                cfg2 = load_config()
                kid = key[-10:]           # 키 전문은 저장하지 않는다
                today = datetime.now().strftime("%Y-%m-%d")

                used = dict(cfg2.get("byteplus_used") or {})          # 누적(참고용)
                used[kid] = int(_num(used.get(kid), 0)) + int(tokens)
                cfg2["byteplus_used"] = used

                daily = dict(cfg2.get("byteplus_daily") or {})        # 날짜별
                day = dict(daily.get(today) or {})
                day[kid] = int(_num(day.get(kid), 0)) + int(tokens)
                daily[today] = day
                # 30일치만 남긴다 (보상 패키지 유효기간과 같은 창)
                for k in sorted(daily.keys())[:-30]:
                    daily.pop(k, None)
                cfg2["byteplus_daily"] = daily
                save_config(cfg2)

            cap = int(_num(cfg2.get("byteplus_daily_cap"), 5_000_000))
            spent = day[kid]
            left = max(0, cap - spent)
            pct = int(spent * 100 / cap) if cap else 0
            if left:
                self._js("vidStatus",
                         f"#{no} {kname} {int(tokens):,}토큰 · 오늘 {spent:,}/{cap:,} ({pct}%) · "
                         f"남은 보상 한도 {left:,}")
            else:
                self._js("vidStatus",
                         f"#{no} ⚠ {kname} 오늘 보상 한도({cap:,}) 초과 — 초과분은 내일 안 돌아옵니다")
        except Exception:
            pass

    # ── 무료 잔량 조회 (관리 OpenAPI) ──────────────────────
    # 콘솔의 모델 ID 는 길고 벤더 접두어가 붙는다(ByteDance-Seedance-1.5-pro,
    # Dola-Seedream-5.0-lite). 화면엔 짧은 한글 이름으로 보여준다.
    # 생성용 ark- 키로는 사용량·잔량을 못 본다(2026-08-10 전 경로 확인).
    # 관리 API 는 AK/SK 볼케이노 v4 서명을 쓴다. 여기서 쓰는 건 ListModelChargeItems —
    # '얼마나 썼나'(GetInferenceUsage)가 아니라 **'얼마나 남았나'**를 바로 준다.
    # 무료 한도가 콜드스타트+데일리로 계속 누적돼서, 소비량에서 역산하면 안 맞는다.
    BP_OPEN_HOST = "open.byteplusapi.com"
    BP_SERVICE = "ark"
    BP_REGION = "ap-southeast-1"

    @classmethod
    def _bp_sign(cls, ak, sk, action, version, body=b"", method="POST"):
        """볼케이노 v4 서명 헤더. 실패 시 예외를 그대로 올린다."""
        import hashlib
        import hmac as _hmac
        from datetime import timezone
        now = datetime.now(timezone.utc)
        xdate = now.strftime("%Y%m%dT%H%M%SZ")
        xdate_short = xdate[:8]
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_query = f"Action={action}&Version={version}"
        signed_headers = "content-type;host;x-content-sha256;x-date"
        NL = "\n"
        hdr_block = (f"content-type:application/json{NL}host:{cls.BP_OPEN_HOST}{NL}"
                     f"x-content-sha256:{payload_hash}{NL}x-date:{xdate}{NL}")
        canonical = NL.join([
            method, "/", canonical_query, hdr_block,
            signed_headers, payload_hash,
        ])
        scope = f"{xdate_short}/{cls.BP_REGION}/{cls.BP_SERVICE}/request"
        to_sign = NL.join(["HMAC-SHA256", xdate, scope,
                             hashlib.sha256(canonical.encode()).hexdigest()])

        def h(key, msg):
            return _hmac.new(key, msg.encode(), hashlib.sha256).digest()

        k = h(sk.encode(), xdate_short)
        k = h(k, cls.BP_REGION)
        k = h(k, cls.BP_SERVICE)
        k = h(k, "request")
        sig = _hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        return {
            "Content-Type": "application/json",
            "Host": cls.BP_OPEN_HOST,
            "X-Date": xdate,
            "X-Content-Sha256": payload_hash,
            "Authorization": (f"HMAC-SHA256 Credential={ak}/{scope}, "
                              f"SignedHeaders={signed_headers}, Signature={sig}"),
        }

    # 잔량 실측 — ListModelChargeItems 의 ResourcePackItems[].(Total − Consumed) 합이
    # 모델별 남은 무료 잔량이고, 콘솔 화면과 정확히 같은 값이다 (2026-08-11 대조 확인:
    # Seedance-1.5-pro 4,912,000/9,955,694 · Seedream-4.5 123/533).
    #
    # ⚠ **PageSize 를 반드시 준다.** 안 주면 기본 10개만 오는데, 정작 ResourcePackItems 를
    #   가진 모델은 뒤쪽에 있어서 "잔량 항목이 하나도 없다"는 잘못된 결론이 나온다
    #   (2026-08-11 실측: 전체 42개 중 값이 담긴 건 4개, 기본 10개 안에는 0개).
    #
    # ⚠ 이 API 는 몇 분 동기화 지연이 있다 — **매 장 조회하면 안 된다.** 방금 만든 것이
    #   아직 안 빠져 있어 초과 생성·과금으로 이어진다. 작업 시작 시 1회 조회로 기준점을
    #   잡고 이후는 앱이 로컬로 차감한다(_track_bp_images·_track_bp_tokens).
    BP_QUOTA_ACTIONS = [
        ("ListModelChargeItems", {"PageSize": 100}, "ResourcePackItems"),
        # 폴백 — 계정에 따라 이쪽에만 담기는 경우를 대비 (지금 계정들은 전부 빈 배열이다)
        ("ListModelActivations", {"PageSize": 100}, "FreeResourcePackItems"),
    ]

    def vid_vers(self, params):
        """컷의 판 목록 — 컷 카드의 [v1][v2][v3] 칩이 쓴다 (2026-08-19).
        파일을 옮기지 않으므로 '어느 게 최신인가'는 폴더를 보고 그때그때 정한다."""
        p = params or {}
        d = (p.get("dir") or "").strip()
        no = int(_num(p.get("no"), 0))
        if not d or not no:
            return {"ok": False, "error": "폴더·컷 번호가 필요합니다"}
        rows = []
        for v, path in vid_versions(d, no):
            pv = os.path.join(os.path.dirname(path), "_미리보기",
                              os.path.splitext(os.path.basename(path))[0] + ".webm")
            rows.append({"v": v, "path": path, "file": os.path.basename(path),
                         "preview": pv if os.path.exists(pv) else "",
                         "mb": round(os.path.getsize(path) / 1e6, 1) if os.path.exists(path) else 0})
        return {"ok": True, "items": rows, "latest": rows[-1]["v"] if rows else 0}

    def _bp_sync_live(self, js_name="imgStatus"):
        """배치 시작 직전 1회 — 계정별 실측 잔량을 조회해 '잔량 0' 계정 목록을 만든다
        (2026-08-19, 사용자 요청). 로컬 추정은 이 앱·이 컴퓨터가 쓴 것만 알아서, 컴퓨터가
        두 대가 되면 '남은 줄 알고 시도 → 무료 바닥 → 조용히 과금' 구멍이 열린다.
        ⚠ 조회 API 는 몇 분 동기화 지연이 있어 **배치당 1회만** 부른다 — 배치 중에는 로컬
        차감으로 간다. 5분 안의 연속 배치(이미지→영상)는 직전 실측을 재사용한다.
        AK/SK 없는 계정은 조회가 안 되므로 지금처럼 로컬 추정만으로 판단한다."""
        try:
            cfg = load_config()
            live = cfg.get("byteplus_live") or {}
            if time.time() - _num(live.get("ts"), 0) < 300:
                return
            r = self.bp_free_quota()
            if not (r and r.get("ok")):
                return
            empty = {"img": {}, "vid": {}}
            note = []
            for row in r.get("accounts") or []:
                il = sum(m["left"] for m in row["models"] if m["unit"] == "장")
                vl = sum(m["left"] for m in row["models"] if m["unit"] == "토큰")
                has_i = any(m["unit"] == "장" for m in row["models"])
                has_v = any(m["unit"] == "토큰" for m in row["models"])
                if has_i and il <= 0:
                    empty["img"][row["tail"]] = True
                if has_v and vl <= 0:
                    empty["vid"][row["tail"]] = True
                tag = []
                if has_v:
                    tag.append(f"{vl:,}t" if vl > 0 else "0t(제외)")
                if has_i:
                    tag.append(f"{il}장" if il > 0 else "0장(제외)")
                note.append(row["name"] + " " + "/".join(tag))
            with _CFG_LOCK:
                c2 = load_config()
                c2["byteplus_live"] = {"ts": time.time(), "empty": empty}
                save_config(c2)
            if note:
                self._js(js_name, "🔎 무료 잔량 실측: " + " · ".join(note[:6]))
        except Exception:
            pass    # 실측 실패는 조용히 — 로컬 추정 방어선이 그대로 동작한다

    def bp_free_quota(self, params=None):
        """모델별 남은 무료 잔량 (실측). 값이 담긴 응답을 못 찾으면 accounts 를 빈 채로
        돌려준다 — 호출부(byteplus_status)가 그걸 보고 로컬 추정으로 되돌아간다."""
        cfg = load_config()
        # 계정마다 무료 쿼터가 따로다 → 계정별 AK/SK 로 각각 조회한다
        accts = [a for a in self._bp_accounts(cfg) if a.get("ak") and a.get("sk")]
        if not accts:
            return {"ok": False, "error": "AK/SK가 없습니다. 계정 줄에 'ak=… | sk=…'을 붙이거나 "
                                          "설정의 공용 AK/SK 칸을 채워주세요."}
        body = json.dumps((params or {}).get("body") or {}, separators=(",", ":")).encode()
        rows, errs = [], []
        # 계정 줄에 ak=/sk= 를 안 적으면 전부 공용 AK/SK 로 폴백한다(_bp_accounts).
        # 그러면 서로 다른 계정 행에 **같은 계정의 잔량**이 각자 이름표를 달고 반복 표시되어,
        # 무료 쿼터가 실제보다 몇 배 있는 것처럼 보인다 → 모르는 새 유료 과금으로 이어진다.
        dup = {}
        for a in accts:
            dup.setdefault((a["ak"], a["sk"]), []).append(a["name"])
        for names in dup.values():
            if len(names) > 1:
                errs.append("⚠ " + "·".join(names) + " 가 같은 AK/SK 로 조회됩니다 — "
                            "계정마다 자기 AK/SK 를 넣으세요. 지금 값은 한 계정의 잔량이 "
                            "여러 계정 이름으로 중복 표시된 것입니다.")
        seen_actions = []
        for a in accts:
            models = []
            for action, extra, pack_key in self.BP_QUOTA_ACTIONS:
                b = json.dumps(dict((params or {}).get("body") or {}, **extra),
                               separators=(",", ":")).encode()
                try:
                    hdr = self._bp_sign(a["ak"], a["sk"], action, "2024-01-01", b)
                    r = requests.post(
                        f"https://{self.BP_OPEN_HOST}/?Action={action}&Version=2024-01-01",
                        headers=hdr, data=b, timeout=40)
                    if r.status_code != 200:
                        continue
                    res = r.json().get("Result") or {}
                except Exception as e:
                    errs.append(f"{a['name']}/{action}: {str(e)[:100]}")
                    continue
                items = res.get("Items") or res.get("ModelChargeItems") or []
                got = []
                for it in items if isinstance(items, list) else []:
                    packs = it.get(pack_key) or []
                    left = total = 0
                    for q in packs:
                        if not isinstance(q, dict):
                            continue
                        t = int(_num(q.get("Total"), 0))
                        total += t
                        left += max(0, t - int(_num(q.get("Consumed"), 0)))
                    if total <= 0:      # 잔량이 안 담긴 항목은 버린다 (0 을 잔량으로 보이면 위험)
                        continue
                    mid = (it.get("DisplayName") or it.get("FoundationModelName")
                           or it.get("ModelId") or it.get("Name") or "?")
                    got.append({"model": mid, "label": bp_model_label(mid),
                                "unit": "장" if bp_is_image(mid) else "토큰",
                                "left": left, "total": total, "packs": len(packs)})
                if got:
                    models = got
                    if action not in seen_actions:
                        seen_actions.append(action)
                    break     # 값이 담긴 응답을 찾았으면 다음 Action 은 안 본다
            # 남은 게 많은 순 — 어느 계정을 먼저 쓸지 눈으로 고르게
            models.sort(key=lambda m: (m["unit"] != "토큰", -m["left"]))
            if models:
                rows.append({"name": a["name"], "tail": a["key"][-6:], "models": models})
        if not rows:
            # 조회는 됐는데 잔량이 안 담겨 있는 상태 — 호출부가 로컬 추정으로 폴백한다
            errs.append("실측 API가 잔량을 주지 않습니다 (ListModelActivations·"
                        "ListModelChargeItems 모두 무료 패키지 항목이 비어 있음) — "
                        "아래 값은 앱이 센 추정치입니다")
            return {"ok": False, "error": " · ".join(errs)[:400], "errors": errs}
        return {"ok": True, "accounts": rows, "errors": errs, "action": seen_actions}

    def byteplus_status(self, params=None):
        """설정 탭 [잔여 확인].

        1순위 = **실측**(ListModelChargeItems). 계정 줄에 ak=/sk= 가 있으면 콘솔과 같은
        모델별 잔량을 그대로 가져온다. 로컬 누적 추정은 앱 밖에서 쓴 양을 모르고 보상
        지급분도 못 봐서 시간이 갈수록 콘솔과 벌어진다 — 실측이 있으면 그걸 보여준다.
        2순위 = 로컬 추정(예전 동작). AK/SK 가 없거나 조회가 실패했을 때의 폴백이다."""
        cfg = load_config()
        # 실측 — 계정마다 API 를 부르므로 몇 초 걸린다. 버튼을 눌렀을 때만 한다.
        live, live_err = {}, []
        if (params or {}).get("live", True):
            try:
                r = self.bp_free_quota()
                if r.get("ok"):
                    for a in (r.get("accounts") or []):
                        live[a["tail"]] = a
                live_err = [e for e in (r.get("errors") or []) if not e.startswith("⚠")]
                live_err = [e for e in live_err if "실측 API가 잔량을" not in e] + \
                           [e for e in (r.get("errors") or []) if "실측 API가 잔량을" in e]
            except Exception as e:
                live_err = [f"실측 조회 실패: {str(e)[:120]}"]
        used = cfg.get("byteplus_used") or {}
        rows = []
        eps = {a["key"]: a["ep"] for a in self._bp_accounts(cfg)}
        iu = cfg.get("byteplus_img_used") or {}
        iq = cfg.get("byteplus_img_quota") or {}
        for kname, key, is_free in self._seedance_keys(cfg, skip_spent=False):
            u = int(_num(used.get(key[-10:]), 0))
            quota = int(_num(cfg.get("byteplus_free_quota"), 5_000_000))
            imgs = []
            for m, dq in SEEDREAM_QUOTA.items():
                q = int(_num(iq.get(m), dq))
                spent = int(_num(iu.get(f"{key[-10:]}|{m}"), 0))
                imgs.append({"model": m.split("-")[0] + " " + m.split("-")[1] + "." + m.split("-")[2],
                             "remain": max(0, q - spent)})
            # 데이터 협업 보상은 전날 쓴 만큼 다음 날 채워진다 → '오늘 얼마 썼나'가 실제 지표다
            today_spent = int(_num(((cfg.get("byteplus_daily") or {}).get(
                datetime.now().strftime("%Y-%m-%d")) or {}).get(key[-10:]), 0))
            cap = int(_num(cfg.get("byteplus_daily_cap"), 5_000_000))
            # 720p 무음 4초 = 86,400 토큰 (가로×세로×24fps/1024 × 4)
            hit = live.get(key[-6:])
            rows.append({"name": kname, "tail": key[-6:], "free": is_free, "used": u,
                         "ep": bool(eps.get(key)),
                         # 실측이 있으면 모델별 [{label, unit, left, total}] — 없으면 None
                         "live": (hit or {}).get("models"),
                         "today": today_spent, "cap": cap,
                         "today_left": max(0, cap - today_spent),
                         "today_clips": max(0, cap - today_spent) // 86_400,
                         "remain": (max(0, quota - u) if is_free else None),
                         "clips": (max(0, quota - u) // 86_400 if is_free else None),
                         "imgs": (imgs if is_free else None)})
        # 계정 줄에 ak=/sk= 를 안 적으면 전부 공용 AK/SK 로 폴백한다(_bp_accounts). 그러면
        # 잔량 실측이 **한 계정 것을 여러 계정 이름으로 반복** 보고해 무료 쿼터가 몇 배 있는
        # 것처럼 보이고, 모르는 새 유료 과금으로 이어진다. 설정 탭에서 바로 보이게 알린다.
        warns, seen = [], {}
        for a in self._bp_accounts(cfg):
            if a.get("ak") and a.get("sk"):
                seen.setdefault((a["ak"], a["sk"]), []).append(a["name"])
        for names in seen.values():
            if len(names) > 1:
                warns.append("·".join(names) + " 가 같은 AK/SK 를 씁니다 — 계정마다 자기 "
                             "AK/SK 를 넣으세요 (지금은 한 계정 잔량이 중복 표시됩니다)")
        if not live and any(not (a.get("ak") and a.get("sk")) for a in self._bp_accounts(cfg)):
            warns.append("AK/SK 가 없는 계정은 실측을 못 합니다 — 아래 값은 앱이 센 추정치라 "
                         "콘솔과 다를 수 있습니다. 계정 줄에 ak=/sk= 를 넣어주세요")
        warns += live_err[:3]
        return {"ok": True, "keys": rows, "warns": warns, "live": bool(live)}

    def _gen_seedance(self, cfg, prompt, first, last, aspect, res, secs, out_path, model, no=0,
                      audio="room", camera_fixed=False, key_offset=0):
        """BytePlus ModelArk Seedance — 태스크 생성 → 폴링 → 다운로드 (Veo 와 같은 3단 구조).
        first: 시작 프레임(없으면 T2V). last: 도착 프레임 — 체인에서 앞 클립 끝(first)에서
        이 컷의 이미지(last)로 '도착'하게 지시해 컷 경계를 모델이 직접 이어준다."""
        import base64, mimetypes
        # 계정들을 순서대로 → 전부 실패하면 유료 키로 폴백 (ep 지정 시 그 계정이 1순위)
        keys = self._seedance_keys(cfg, model)
        # 병렬 생성용 계정 분산 — 묶음마다 키 순서를 어긋나게 돌려, 동시에 도는 묶음들이
        # 같은 계정부터 두드리지 않게 한다 (무료 쿼터 동시 소비·계정별 서버 큐 정체 방지).
        # ⚠ 회전은 **살아있는 무료 계정 구간만** — 목록 꼬리의 유료 폴백·(소진) 안전망이
        # 회전으로 1순위가 되면 무료가 멀쩡한데 과금된다 (_gen_seedream 과 같은 원칙).
        if key_offset and keys:
            lead = 0
            for _kn, _k, _free in keys:
                if not _free or _kn.endswith("(소진)"):
                    break
                lead += 1
            if lead > 1:
                _off = key_offset % lead
                keys = keys[_off:lead] + keys[:_off] + keys[lead:]
        if not keys:
            if (cfg.get("byteplus_on_empty") or "paid") == "stop":
                raise RuntimeError("무료 쿼터를 모두 소진했습니다 — 설정에서 '유료로 계속'을 선택하거나 "
                                   "내일 보상 지급 후 다시 시도하세요")
            raise RuntimeError("설정 탭에 BytePlus Ark 키를 넣어주세요 (Seedance 영상)")
        base = (cfg.get("byteplus_base") or "").strip() or "https://ark.ap-southeast.bytepluses.com/api/v3"
        # Seedance 는 해상도·길이·비율을 프롬프트 뒤 --인자로 받는다 (2026-08-05 실측 검증)
        # 사용자가 쓴 프롬프트에 '--' 가 섞이면 Seedance 가 파라미터로 오해한다 → 미리 걷어낸다
        prompt = re.sub(r"-{2,}", "—", prompt or "").strip()
        text = f"{prompt} --resolution {res} --duration {int(_num(secs, 5))} --ratio {aspect} --watermark false"
        if camera_fixed:
            text += " --camerafixed true"   # '고정' 카메라 컷 — Seedance가 멋대로 움직이지 않게

        def _img(p, role):
            mt = mimetypes.guess_type(p)[0] or "image/png"
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}, "role": role}

        content = [{"type": "text", "text": text}]
        if first and os.path.exists(first):
            content.append(_img(first, "first_frame"))
            if last and os.path.exists(last) and os.path.abspath(last) != os.path.abspath(first):
                content.append(_img(last, "last_frame"))
        body = {"model": model, "content": content}
        # 엔드포인트(ep-…)는 어느 모델인지 이름으로 알 수 없다 → 설정의 지정값을 따른다
        gen_audio = "1-5" in model or (
            str(model).startswith("ep-") and (cfg.get("byteplus_ep_audio") or "1") == "1")
        if gen_audio:   # 1.5부터 오디오 생성 — room(나레이션용)은 무음이 안전
            body["generate_audio"] = (audio == "sfx")
        tid, headers, last_err, key_used = None, None, "", None
        for i, (kname, key, is_free) in enumerate(keys):
            hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            try:
                r = requests.post(f"{base}/contents/generations/tasks", headers=hdr, json=body, timeout=120)
            except Exception as e:
                last_err = str(e)[:180]
                continue
            if r.status_code == 200 and (r.json() or {}).get("id"):
                tid, headers, key_used = r.json()["id"], hdr, (kname, key, is_free)
                if i > 0:
                    self._js("vidStatus", f"#{no} 💳 {kname} 키로 생성합니다")
                break
            last_err = f"{r.status_code} {(r.text or '')[:400]}"
            # 프롬프트 자체를 거부한 경우(content.text) — 키를 바꿔봐야 똑같다.
            # 지시문을 걷어내고 '무엇이 어떻게 변하는가'만 남겨 1회 재시도한다.
            if "content.text" in last_err or "Invalid content" in last_err:
                # 지시문(스타일·템포·오디오·네거티브)만 걷어내고 '무엇이 어떻게 변하는가'는 살린다.
                # 단순 [0] 은 템플릿마다 엉뚱한 블록을 집었다 — I2V 는 "Animate the provided
                # start frame." 한 줄만, T2V 는 Shot/Camera 만 남아 연출이 통째로 사라졌다.
                # 그 상태로 재시도가 통과하면 지시 없는 클립이 정상처럼 저장되고 과금된다 (2026-08-13).
                blocks = re.split(r"\n{2,}", prompt)
                core = [b for b in blocks if re.match(r"\s*(Shot:|Camera:|SUBJECT:|Motion:)", b)]
                short = ("\n".join(core) or blocks[0])[:600].strip() or "the scene comes alive"
                slim = f"{short} --resolution {res} --duration {int(_num(secs, 5))} --ratio {aspect} --watermark false"
                self._js("vidStatus", f"#{no} ⚠ 프롬프트가 거부돼 단순화해 재시도합니다")
                try:
                    body2 = dict(body, content=[{"type": "text", "text": slim}] + body["content"][1:])
                    r2 = requests.post(f"{base}/contents/generations/tasks", headers=hdr, json=body2, timeout=120)
                    if r2.status_code == 200 and (r2.json() or {}).get("id"):
                        tid, headers, key_used = r2.json()["id"], hdr, (kname, key, is_free)
                        break
                    last_err = f"{r2.status_code} {(r2.text or '')[:400]}"
                except Exception as e:
                    last_err = str(e)[:180]
                continue
            if i < len(keys) - 1:
                self._js("vidStatus", f"#{no} ⚠ {kname} 키 실패({r.status_code}) — 다음 키로 전환")
        if not tid:
            raise RuntimeError(last_err or "태스크 ID를 받지 못했습니다")
        # 대기 한도 — 720p 단독 컷은 10분이면 넉넉하지만, 1080p 이상이나 도착 프레임
        # (조립·체인)이 걸리면 서버가 10분을 자주 넘긴다 (2026-08-19 제보: 1080p+조립
        # 컷만 매번 '시간 초과'). 그런 컷은 25분까지 기다린다.
        wait_s = 1500 if (last or str(res) != "720p") else 600
        deadline = time.time() + wait_s
        st = None
        while time.time() < deadline:
            if not self.vid_running:
                raise RuntimeError("사용자 중단")
            time.sleep(8)
            try:
                q = requests.get(f"{base}/contents/generations/tasks/{tid}", headers=headers, timeout=60)
            except Exception:
                continue
            if q.status_code != 200:
                continue
            d = q.json() or {}
            st = d.get("status")
            if st == "succeeded":
                url = (d.get("content") or {}).get("video_url") or ""
                if not url:
                    raise RuntimeError("영상 URL이 없습니다")
                v = requests.get(url, timeout=300)
                v.raise_for_status()
                with open(out_path, "wb") as f:
                    f.write(v.content)
                # 사용 토큰 누적 → 무료 키 잔여 추정 갱신
                if key_used:
                    tok = _num((d.get("usage") or {}).get("completion_tokens"), 0)
                    if tok:
                        self._track_bp_tokens(key_used[1], key_used[0], key_used[2], tok, no)
                return out_path
            if st in ("failed", "cancelled", "expired"):
                raise RuntimeError(f"Seedance {st}: {str(d.get('error') or '')[:150]}")
        raise RuntimeError(f"시간 초과 ({wait_s // 60}분) — 마지막 서버 상태: {st or '응답 없음'}")

    def _gen_veo(self, cfg, prompt, image_path, aspect, res, secs, out_path, model, no=0,
                 last_path=None):
        """predictLongRunning — 작업 제출 → 폴링 → 파일 다운로드."""
        import base64, mimetypes
        headers = {"x-goog-api-key": cfg["gemini_key"], "Content-Type": "application/json"}
        inst = {"prompt": prompt}
        # 시작 프레임은 호출부(_generate_videos)에서 확정됨 — 프롬프트가 I2V/T2V 로 갈리기 때문
        if image_path and os.path.exists(image_path):
            try:
                mt = mimetypes.guess_type(image_path)[0] or "image/png"
                with open(image_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                # 문서는 image.inlineData 라고 하지만 Veo 3.1 은 그걸 거부한다 (400).
                # 실측 결과 predict 계열 표준인 bytesBase64Encoded 만 수락된다 (2026-08-04).
                inst["image"] = {"bytesBase64Encoded": b64, "mimeType": mt}
            except Exception:
                pass
        # ⛓ 도착 프레임 — 키 확정(2026-08-10): 공식 google-genai SDK 직렬화 코드 검증 결과
        # Developer API 는 instances[0].lastFrame = {bytesBase64Encoded, mimeType} 다
        # (_GenerateVideosParameters_to_mldev → _Image_to_mldev). 1순위 키가 정답이고,
        # 뒤 후보들은 모델이 보간을 지원하지 않을 때(lite 등)의 안전망으로만 남긴다.
        veo_last = None
        if last_path and os.path.exists(last_path):
            try:
                mt2 = mimetypes.guess_type(last_path)[0] or "image/png"
                with open(last_path, "rb") as f:
                    veo_last = {"bytesBase64Encoded": base64.b64encode(f.read()).decode(),
                                "mimeType": mt2}
            except Exception:
                veo_last = None
        # 시작+도착 보간은 **8초 전용** (2026-08-18 실측: 4·6초는 키 이름 없는 일반 400
        # "use case not supported" 로 통째 거부 → 예전엔 그 컷이 그대로 실패했다).
        # 8초가 아니면 도착 프레임만 빼고 진행한다 — 이음매는 어긋나도 컷은 산다.
        if veo_last and int(_num(secs, 4)) != 8:
            self._js("vidStatus", f"#{no} ⚠ Veo 도착 프레임(보간)은 8초 전용 — 도착 지정 없이 생성합니다")
            veo_last = None
        last_keys = ["lastFrame", "last_frame", "endImage"] if veo_last else []
        if last_keys:
            inst[last_keys[0]] = veo_last
        # 문서와 실제 API가 어긋나는 지점들 (2026-08-04 실측):
        #  · durationSeconds 는 **숫자**여야 한다 (문서 예시는 "4" 문자열 → 400)
        #  · numberOfVideos 는 Veo 3.1 이 받지 않는다 (보내면 400)
        # 파라미터가 거부되면 그 키만 빼고 1회 재시도한다 — 모델별 지원 차이가 계속 생긴다.
        params = {"aspectRatio": aspect, "resolution": res, "durationSeconds": _num(secs, 4)}
        r = None
        for _ in range(4):
            r = requests.post(f"{GEMINI_REST}/models/{model}:predictLongRunning",
                              headers=headers, json={"instances": [inst], "parameters": params},
                              timeout=120)
            if r.status_code != 400:
                break
            # 도착 프레임 키가 거부되면 다음 후보로, 다 떨어지면 빼고 진행(시작 프레임만).
            # 에러 문구에 그 키 이름이 있을 때만 뺀다 — 예전 조건('Unknown name'만 있어도)은
            # durationSeconds 등 다른 파라미터 문제인데 lastFrame 부터 빼는 오판을 했다.
            cur = next((k for k in last_keys if k in inst), None)
            # 일반 400("use case not supported")에 도착 프레임이 걸려 있으면 그걸 의심하고
            # 빼서 1회 재시도 — 키 이름이 문구에 없어 기존 조건으로는 못 잡던 거부다.
            if cur and "use case is currently not supported" in (r.text or ""):
                inst.pop(cur, None)
                last_keys = []
                self._js("vidStatus", f"#{no} ⚠ Veo 가 도착 프레임 조합을 거부 — 시작 프레임만으로 재시도")
                continue
            if cur and cur in (r.text or ""):
                inst.pop(cur, None)
                nxt_i = last_keys.index(cur) + 1
                if nxt_i < len(last_keys):
                    inst[last_keys[nxt_i]] = veo_last
                    self._js("vidStatus", f"#{no} ⛓ 도착 프레임 키 '{cur}' 거부 → '{last_keys[nxt_i]}' 재시도")
                else:
                    self._js("vidStatus", f"#{no} ⚠ Veo 도착 프레임을 못 붙여 시작 프레임만으로 진행합니다")
                continue
            m = re.search(r"`(\w+)` isn't supported", r.text or "")
            if m and m.group(1) in params:
                params.pop(m.group(1))
                continue
            # 시작 프레임(image) 형식이 거부되면 이미지 없이라도 생성되게 한다.
            # 톤은 프롬프트에도 들어 있으므로 완전 실패보다 낫다.
            if m and "image" in inst and m.group(1) in ("inlineData", "imageBytes", "bytesBase64Encoded", "image"):
                inst.pop("image", None)
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {(r.text or '')[:200]}")
        op = (r.json() or {}).get("name")
        if not op:
            raise RuntimeError("작업 ID를 받지 못했습니다")

        # 폴링 — Veo는 보통 1~3분. 최대 10분까지 기다린다.
        deadline = time.time() + 600
        data = {}
        while time.time() < deadline:
            if not self.vid_running:
                raise RuntimeError("사용자 중단")
            time.sleep(10)
            q = requests.get(f"{GEMINI_REST}/{op}", headers=headers, timeout=60)
            if q.status_code != 200:
                continue
            data = q.json() or {}
            if data.get("done"):
                break
            left = int(deadline - time.time())
            self._js("vidStatus", f"#{no} 생성 중… (남은 대기 {left//60}분 {left%60}초)")
        if not data.get("done"):
            raise RuntimeError("시간 초과 (10분) — 나중에 다시 시도하세요")
        if data.get("error"):
            raise RuntimeError(str(data["error"])[:200])

        samples = (((data.get("response") or {}).get("generateVideoResponse") or {})
                   .get("generatedSamples") or [])
        uri = (samples[0].get("video") or {}).get("uri") if samples else None
        if not uri:
            raise RuntimeError("응답에 영상이 없음 (안전 필터 차단 가능성)")
        d = requests.get(uri, headers={"x-goog-api-key": cfg["gemini_key"]},
                         timeout=300, stream=True)
        if d.status_code != 200:
            raise RuntimeError(f"다운로드 실패 {d.status_code}")
        with open(out_path, "wb") as f:
            for chunk in d.iter_content(1 << 16):
                if chunk:
                    f.write(chunk)
        return out_path

    @staticmethod
    def _img_err(msg):
        """이미지 API 오류를 사용자가 조치 가능한 문구로 (PRD 7.3)."""
        m = msg or ""
        if "403" in m or "PERMISSION_DENIED" in m or "billing" in m.lower():
            return "이미지 생성은 결제 등록(Tier 1)이 필요합니다 — aistudio.google.com에서 billing 활성화 후 다시 시도하세요"
        if "429" in m or "RESOURCE_EXHAUSTED" in m:
            return "요청이 많아 거절됐습니다(429). 잠시 후 다시 시도하세요"
        if "안전" in m or "SAFETY" in m.upper() or "이미지가 없음" in m:
            return "안전 필터에 걸렸을 수 있습니다 — 프롬프트를 순화해 재생성하세요"
        if "404" in m:
            return "모델을 찾을 수 없습니다(404) — 설정에서 다른 모델을 선택하세요"
        if "content.text" in m or "Invalid content" in m:
            # 원문을 반드시 남긴다 — 어느 파라미터를 왜 거부했는지는 응답에만 있는데
            # 예전엔 고정 문구로 덮어써서 원인 추적이 불가능했다 (2026-08-13).
            return "프롬프트를 모델이 거부했습니다 — API 응답: " + m[:400]
        if "ModelNotOpen" in m:
            return "이 계정에서 해당 모델이 활성화되지 않았습니다 — BytePlus 콘솔에서 모델을 켜세요"
        return m[:200]

    # ── 모델 어댑터 (PRD 7.1.2 — 교체는 함수 하나 추가로 끝나게) ──
    def _gen_image(self, cfg, prompt, ref_paths, aspect, out_base, model=None, size=None, rot=0):
        """out_base = 확장자 없는 경로. 실제 저장된 경로(확장자 포함)를 반환한다.
        rot = 병렬 배치에서의 작업 순번 — Seedream 키 순서를 회전시켜 계정에 부하를 편다."""
        # 모델 id 로 엔진을 가른다 — 컷마다 다른 엔진을 쓸 수 있게 (설정의 provider 는 기본값)
        mid = model or cfg.get("img_model") or ""
        # 해상도를 그 모델이 실제로 받는 값으로 맞춘다. UI 가 모델별 목록으로 그려주지만
        # 저장된 설정·재생성·배치 밖 호출은 옛 값을 그대로 들고 올 수 있다 (영상 길이와 같은 계열의
        # 사고: 2026-08-14 에 Veo 표를 Seedance 에 적용해 10초가 4초로 눌렸다).
        allow = IMG_SIZES_BY_MODEL.get(mid)
        if allow:
            cur = (size or cfg.get("img_size") or "").strip().upper()
            if cur not in allow:
                # 가장 가까운 값으로 — 숫자만 뽑아 비교한다 ('2K'→2, '0.5K'→0.5)
                def _n(x):
                    try:
                        return float(re.sub(r"[^0-9.]", "", x) or 0)
                    except Exception:
                        return 0.0
                size = min(allow, key=lambda a: abs(_n(a) - _n(cur))) if cur else allow[0]
            else:
                size = cur
        if bp_is_image(mid) or (not mid and cfg.get("img_provider") == "seedream"):
            return self._gen_seedream(cfg, prompt, ref_paths, aspect, out_base, model, size, rot)
        return self._gen_gemini(cfg, prompt, ref_paths, aspect, out_base, model, size)

    def _gen_seedream(self, cfg, prompt, ref_paths, aspect, out_base, model=None, size=None, rot=0):
        """BytePlus Seedream — 영상과 같은 계정/키를 쓰므로 무료 쿼터·보상 캠페인이 그대로 적용된다.
        토큰이 아니라 **장당** 과금이고 최소 픽셀 제한(약 369만)이 있어 크게만 뽑힌다."""
        import base64, mimetypes
        model = model or "seedream-5-0-260128"
        keys = self._seedance_keys(cfg, model)
        if not keys:
            raise RuntimeError("설정 탭에 BytePlus 계정을 넣어주세요 (Seedream 이미지)")
        # 병렬 배치 — 워커마다 다른 무료 계정부터 시도해 부하·무료 쿼터를 고르게 편다.
        # 회전은 '살아있는 무료 계정' 구간만: 유료 키·(소진) 안전망이 앞으로 오면 안 된다.
        if rot:
            lead = 0
            for kname, _k, is_free in keys:
                if not is_free or kname.endswith("(소진)"):
                    break
                lead += 1
            if lead > 1:
                r = rot % lead
                keys = keys[r:lead] + keys[:r] + keys[lead:]
        base = (cfg.get("byteplus_base") or "").strip() or "https://ark.ap-southeast.bytepluses.com/api/v3"
        # 해상도 — **항상 WIDTHxHEIGHT 로 보낸다.**
        # API 는 '2k' 같은 티어도 받지만, 그러면 비율을 모델이 제멋대로 정한다
        # (2026-08-16 실사고: 9:16 요청에 2848x1600·2048x2048 이 나왔다).
        # 티어는 seedream_size() 가 비율과 합쳐 픽셀로 바꾼다 — 해상도 선택도 그대로 살아 있다.
        tier = (size or "").strip().upper()
        if tier not in IMG_SIZES_BY_MODEL.get(model, []):
            tier = "2K"
        size_val = seedream_size(tier, aspect)
        body = {"model": model, "prompt": prompt, "size": size_val,
                "response_format": "url", "watermark": False}
        # 톤 레퍼런스 — Seedream 은 image 필드로 참조 이미지를 받는다 (있으면 그 톤을 따라간다)
        refs = []
        for rp in (ref_paths or [])[:3]:
            try:
                mt = mimetypes.guess_type(rp)[0] or "image/png"
                with open(rp, "rb") as f:
                    refs.append(f"data:{mt};base64," + base64.b64encode(f.read()).decode())
            except Exception:
                pass
        if refs:
            body["image"] = refs if len(refs) > 1 else refs[0]

        last_err, url, key_used = "", "", None
        for i, (kname, key, is_free) in enumerate(keys):
            hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            try:
                r = requests.post(f"{base}/images/generations", headers=hdr, json=body, timeout=240)
            except Exception as e:
                last_err = str(e)[:180]
                continue
            if r.status_code == 200:
                d = r.json() or {}
                url = ((d.get("data") or [{}])[0]).get("url") or ""
                if url:
                    key_used = (kname, key, is_free)
                    if i > 0:
                        self._js("imgStatus", f"💳 {kname} 계정으로 생성합니다")
                    break
            last_err = f"{r.status_code} {(r.text or '')[:180]}"
        if not url:
            raise RuntimeError(last_err or "이미지 URL을 받지 못했습니다")
        v = requests.get(url, timeout=180)
        v.raise_for_status()
        out = out_base + _img_ext(v.content, v.headers.get("Content-Type"))
        with open(out, "wb") as f:
            f.write(v.content)
        # 장당 과금 — 영상 토큰 통과 섞지 않고 모델별 '장수'로 따로 센다
        if key_used and key_used[2]:
            self._track_bp_images(key_used[1], key_used[0], model)
        return out

    def _gen_gemini(self, cfg, prompt, ref_paths, aspect, out_base, model=None, size=None):
        import base64, mimetypes
        model = model or cfg.get("img_model") or "gemini-3.1-flash-image"
        size = size or cfg.get("img_size") or "2K"
        parts = [{"text": prompt}]
        for rp in (ref_paths or [])[:3]:
            try:
                mt = mimetypes.guess_type(rp)[0] or "image/png"
                with open(rp, "rb") as f:
                    parts.append({"inline_data": {"mime_type": mt,
                                                  "data": base64.b64encode(f.read()).decode()}})
            except Exception:
                pass
        url = f"{GEMINI_REST}/models/{model}:generateContent"
        headers = {"x-goog-api-key": cfg["gemini_key"], "Content-Type": "application/json"}

        def _post(modalities):
            body = {"contents": [{"parts": parts}],
                    "generationConfig": {"responseModalities": modalities,
                                         "imageConfig": {"aspectRatio": aspect, "imageSize": size}}}
            return requests.post(url, headers=headers, json=body, timeout=240)

        r = None
        for attempt in range(3):   # 429/5xx 지수 백오프 (PRD 7.3)
            r = _post(["IMAGE"])
            if r.status_code == 400 and "modalit" in (r.text or "").lower():
                r = _post(["TEXT", "IMAGE"])   # 모델별 요구 차이 대응
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt * 2)
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {(r.text or '')[:200]}")
        for c in (r.json().get("candidates") or []):
            for pt in (c.get("content", {}).get("parts") or []):
                d = pt.get("inlineData") or pt.get("inline_data")
                if d and d.get("data"):
                    raw = base64.b64decode(d["data"])
                    # 응답이 PNG가 아닐 수 있다(실측: lite가 JPEG 반환) → 실제 포맷대로 확장자를 붙인다
                    path = out_base + _img_ext(raw, d.get("mimeType") or d.get("mime_type"))
                    # 재생성 때 포맷이 바뀌면 이전 확장자 파일이 남아 같은 컷이 2장이 된다 → 정리
                    for old in (".png", ".jpg", ".webp"):
                        if old != os.path.splitext(path)[1] and os.path.exists(out_base + old):
                            try: os.remove(out_base + old)
                            except Exception: pass
                    with open(path, "wb") as f:
                        f.write(raw)
                    return path
        raise RuntimeError("응답에 이미지가 없음 (안전 필터 차단 가능성)")


from PySide6.QtCore import QObject, Signal, Slot, QUrl, Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebChannel import QWebChannel


class Bridge(QObject):
    '''JS ↔ Python 브릿지. 워커 스레드에 상주 → 느린 호출도 GUI 안 막음.'''
    runJs = Signal(str)

    def __init__(self, api):
        super().__init__()
        self.api = api

    @Slot(str, str, result=str)
    def call(self, name, args_json):
        try:
            fn = getattr(self.api, name, None)
            if fn is None:
                return json.dumps(None)
            res = fn(json.loads(args_json)) if args_json else fn()
            return json.dumps(res, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)[:200]}, ensure_ascii=False)


class JsRunner(QObject):
    '''메인 스레드에서 JS 실행 (푸시 업데이트: addLog/renderReels 등).'''
    def __init__(self, view):
        super().__init__()
        self.view = view

    @Slot(str)
    def run(self, js):
        try: self.view.page().runJavaScript(js)
        except Exception: pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon_path = os.path.join(RES_DIR, "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    view = QWebEngineView()
    view.setWindowTitle("통합 수집기")
    view.resize(1180, 760)
    view.setMinimumSize(980, 640)
    # 로컬 페이지(file://)에서 원격 썸네일(유튜브/인스타) 로딩 허용
    _st = view.settings()
    _st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
    _st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    # 복사 버튼이 실제로 동작하려면 이게 필요하다. QtWebEngine 은 기본이 꺼짐이라
    # execCommand('copy') 가 조용히 false 만 돌려주고 클립보드는 그대로다 — 오류도 안 난다.
    # (2026-08-13 실측: 자막 복사·낭독본 복사·지침 복사가 전부 무반응이었다.
    #  navigator.clipboard 는 file:// 이 보안 컨텍스트가 아니라 아예 못 쓴다.)
    _st.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
    _st.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)

    # CSV 등 다운로드 처리 (QtWebEngine 기본 차단 → 저장 위치 선택창)
    def _on_download(item):
        name = item.suggestedFileName() or "download.csv"
        default = os.path.join(os.path.join(os.path.expanduser("~"), "Downloads"), name)
        path, _ = QFileDialog.getSaveFileName(view, "저장 위치 선택", default, "CSV 파일 (*.csv);;모든 파일 (*.*)")
        if path:
            item.setDownloadDirectory(os.path.dirname(path))
            item.setDownloadFileName(os.path.basename(path))
            item.accept()
        else:
            item.cancel()
    view.page().profile().downloadRequested.connect(_on_download)

    api = Api()
    bridge = Bridge(api)                   # 메인 스레드 상주 (QWebChannel 반환값 정상 전달)

    runner = JsRunner(view)
    # 푸시는 Api 워커 스레드에서 emit → 큐드 연결로 메인 스레드에서 runJavaScript 실행
    bridge.runJs.connect(runner.run, Qt.QueuedConnection)
    api._emit = bridge.runJs.emit

    channel = QWebChannel()
    channel.registerObject("backend", bridge)
    view.page().setWebChannel(channel)

    view.load(QUrl.fromLocalFile(os.path.join(RES_DIR, "ui", "index.html")))
    view.show()
    sys.exit(app.exec())
