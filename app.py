# 통합 수집기 — 릴스 / 유튜브 / 커뮤니티 / 설정  (CustomTkinter 데스크톱 앱)
# 1단계: 앱 골격 + 설정(키 저장) + 커뮤니티 크롤러 이식
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import json, os, threading, random, time, re
from datetime import datetime
from urllib.parse import urljoin

import requests
import urllib3
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# ────────────────── 설정(키) 저장/로드 ──────────────────
DEFAULT_CONFIG = {
    "gemini_key": "",
    "apify_token": "",
    "brightdata_proxy_user": "",
    "brightdata_proxy_pass": "",
    "brightdata_unlocker_key": "",
    "brightdata_unlocker_zone": "web_unlocker2",
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")))
        except Exception as e:
            print("config 로드 실패:", e)
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CONFIG = load_config()

# ────────────────── 커뮤니티 크롤러 (이식) ──────────────────
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-G991N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]


def rand_headers(referer=None):
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "identity",
        "Referer": referer or "https://www.google.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    }


def make_proxy():
    u = CONFIG.get("brightdata_proxy_user", "")
    p = CONFIG.get("brightdata_proxy_pass", "")
    if not u or not p:
        return None
    sid = random.randint(1, 999_999)
    url = f"http://{u}-session-{sid}:{p}@brd.superproxy.io:33335"
    return {"http": url, "https": url}


def unlocker_request(url):
    key = CONFIG.get("brightdata_unlocker_key", "")
    if not key:
        raise RuntimeError("설정에 BrightData Web Unlocker 키가 없습니다.")
    payload = {"zone": CONFIG.get("brightdata_unlocker_zone", "web_unlocker2"), "url": url, "format": "raw"}
    r = requests.post("https://api.brightdata.com/request", json=payload,
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        raise RuntimeError(f"Web Unlocker 실패 {r.status_code}")
    return r.text


scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})


def parse_qoo(html, page, site="더쿠"):
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    tbody = soup.select_one("table.theqoo_board_table > tbody.hide_notice")
    if not tbody:
        return posts
    for tr in tbody.find_all("tr", recursive=False):
        if any(c.startswith("notice") for c in (tr.get("class") or [])):
            continue
        a, dt, vw = tr.select_one("td.title a"), tr.select_one("td.time"), tr.select_one("td.m_no")
        if not (a and dt and vw):
            continue
        cm = tr.select_one("a.replyNum")
        posts.append({"title": a.get_text(strip=True), "link": urljoin("https://theqoo.net", a["href"]),
                      "date": dt.get_text(strip=True), "views": vw.get_text(strip=True),
                      "comments": cm.get_text(strip=True) if cm else "0", "site": site})
    return posts


def parse_fmk(html, page, site="펨코"):
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for tr in soup.select("tbody > tr"):
        a = tr.select_one("td.title a")
        dt, vw = tr.select_one("td.time"), tr.select_one("td.m_no")
        if "notice" in (tr.get("class") or []) or not (a and dt and vw):
            continue
        cm = tr.select_one("a.replyNum")
        posts.append({"title": a.get_text(strip=True), "link": urljoin("https://www.fmkorea.com", a["href"]),
                      "date": dt.get_text(strip=True), "views": vw.get_text(strip=True),
                      "comments": cm.get_text(strip=True) if cm else "0", "site": site})
    return posts


def parse_dc(html, page, site="디씨"):
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for tr in soup.select("tbody.listwrap2 tr.us-post"):
        if "icon_notice" in tr.get("data-type", ""):
            continue
        a, dt, vw = tr.select_one("td.gall_tit a"), tr.select_one("td.gall_date"), tr.select_one("td.gall_count")
        if not (a and dt and vw):
            continue
        cm = tr.select_one("span.reply_num")
        posts.append({"title": re.sub(r"^\[[^\]]+\]\s*", "", a.get_text(strip=True)),
                      "link": urljoin("https://gall.dcinside.com", a["href"]),
                      "date": dt.get_text(strip=True), "views": vw.get_text(strip=True),
                      "comments": cm.get_text(strip=True).strip("[]") if cm else "0", "site": site})
    return posts


def select_parser(url):
    if "theqoo.net" in url:
        return parse_qoo, "더쿠"
    if "fmkorea.com" in url:
        return parse_fmk, "펨코"
    if "dcinside.com" in url:
        return parse_dc, "디씨"
    raise ValueError("지원하지 않는 사이트 (더쿠/펨코/디씨)")


# ────────────────── GUI ──────────────────
GREEN = "#16b364"
GREEN_D = "#0f9152"
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

app = ctk.CTk()
app.title("통합 수집기")
app.geometry("900x680")
FONT = ("맑은 고딕", 12)

header = ctk.CTkFrame(app, fg_color="transparent")
header.pack(fill="x", padx=20, pady=(16, 8))
ctk.CTkLabel(header, text="🟩 통합 수집기", font=("맑은 고딕", 20, "bold")).pack(side="left")
ctk.CTkLabel(header, text="릴스 · 유튜브 · 커뮤니티 스크립트/데이터 수집",
             font=("맑은 고딕", 11), text_color="#6b7280").pack(side="left", padx=12)

tabs = ctk.CTkTabview(app, fg_color="#ffffff", segmented_button_selected_color=GREEN,
                      segmented_button_selected_hover_color=GREEN_D)
tabs.pack(fill="both", expand=True, padx=20, pady=(0, 16))
for name in ["릴스", "유튜브", "커뮤니티", "설정"]:
    tabs.add(name)

# ── 릴스 탭 (다음 단계) ──
ctk.CTkLabel(tabs.tab("릴스"), text="🎬 릴스 스크립트 추출 — 3단계에서 연결 (BrightData 인스타 + Gemini)",
             font=FONT, text_color="#6b7280").pack(pady=40)

# ── 유튜브 탭 (다음 단계) ──
ctk.CTkLabel(tabs.tab("유튜브"), text="▶ 유튜브 자막 추출 — 2단계에서 연결 (yt-dlp)",
             font=FONT, text_color="#6b7280").pack(pady=40)

# ── 커뮤니티 탭 (기능 이식) ──
ct = tabs.tab("커뮤니티")
crawl_state = {"running": False, "results": [], "stats": {"ok": 0, "total": 0}}

top = ctk.CTkFrame(ct, fg_color="transparent")
top.pack(fill="x", padx=10, pady=10)
SITES = [("더쿠", "https://theqoo.net/hot"),
         ("펨코", "https://www.fmkorea.com/humor"),
         ("디씨", "https://gall.dcinside.com/board/lists/?id=dcbest")]
url_var = tk.StringVar()
for label, u in SITES:
    ctk.CTkButton(top, text=label, width=70, fg_color=GREEN, hover_color=GREEN_D,
                  command=lambda x=u: url_var.set(x)).pack(side="left", padx=4)
ctk.CTkEntry(top, textvariable=url_var, placeholder_text="URL (버튼 클릭 또는 직접 입력)",
             width=380).pack(side="left", padx=8)

row2 = ctk.CTkFrame(ct, fg_color="transparent")
row2.pack(fill="x", padx=10)
sp_var, ep_var = tk.StringVar(value="1"), tk.StringVar(value="5")
ctk.CTkLabel(row2, text="페이지", font=FONT).pack(side="left")
ctk.CTkEntry(row2, textvariable=sp_var, width=50).pack(side="left", padx=4)
ctk.CTkLabel(row2, text="~").pack(side="left")
ctk.CTkEntry(row2, textvariable=ep_var, width=50).pack(side="left", padx=4)
proxy_var = tk.BooleanVar(value=True)
ctk.CTkCheckBox(row2, text="프록시 사용", variable=proxy_var, font=FONT).pack(side="left", padx=12)

log = ctk.CTkTextbox(ct, height=260, font=("Consolas", 11))
log.pack(fill="both", expand=True, padx=10, pady=10)


def logmsg(m):
    app.after(0, lambda: (log.insert("end", f"[{datetime.now():%H:%M:%S}] {m}\n"), log.see("end")))


def crawl_worker(url, sp, ep, use_proxy):
    crawl_state["running"] = True
    crawl_state["results"] = []
    crawl_state["stats"] = {"ok": 0, "total": 0}
    try:
        parser, site = select_parser(url)
    except Exception as e:
        logmsg(f"❌ {e}")
        crawl_state["running"] = False
        return
    prev = url
    for page in range(sp, ep + 1):
        if not crawl_state["running"]:
            logmsg("🛑 중단됨")
            break
        crawl_state["stats"]["total"] += 1
        sep = "&" if "?" in url else "?"
        purl = url if page == 1 else f"{url}{sep}page={page}"
        rows = None
        for attempt in range(1, 4):
            try:
                if "theqoo.net" in url and attempt >= 2:
                    html = unlocker_request(purl)
                else:
                    r = scraper.get(purl, headers=rand_headers(prev),
                                    proxies=make_proxy() if use_proxy else None, timeout=15, verify=False)
                    html = r.text
                rows = parser(html, page, site)
                if rows:
                    break
            except Exception as e:
                logmsg(f"⚠ p{page} 시도{attempt} → {e}")
                time.sleep(random.uniform(3, 6))
        if rows:
            for it in rows:
                crawl_state["results"].append([it["title"], it["link"], it["date"], it["views"], it["comments"], it["site"]])
            crawl_state["stats"]["ok"] += 1
            logmsg(f"✓ {site} {page}p — {len(rows)}개")
            prev = purl
            time.sleep(random.uniform(3, 6))
        else:
            logmsg(f"✗ {site} {page}p 실패")
    logmsg(f"✅ 완료 {crawl_state['stats']['ok']}/{crawl_state['stats']['total']}")
    crawl_state["running"] = False
    if crawl_state["results"]:
        save_excel()


def save_excel():
    if not crawl_state["results"]:
        return
    fn = os.path.join(BASE_DIR, f"커뮤니티글_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    df = pd.DataFrame(crawl_state["results"], columns=["제목", "링크", "날짜", "조회수", "댓글수", "사이트"])
    df.to_excel(fn, index=False)
    logmsg(f"💾 저장: {fn}")
    try:
        os.startfile(fn)
    except Exception:
        pass


def start_crawl():
    url = url_var.get().strip()
    if not url:
        messagebox.showerror("오류", "URL을 입력/선택하세요.")
        return
    try:
        sp, ep = int(sp_var.get()), int(ep_var.get())
    except ValueError:
        messagebox.showerror("오류", "페이지는 숫자여야 합니다.")
        return
    if proxy_var.get() and not make_proxy():
        messagebox.showwarning("프록시 없음", "설정에 BrightData 프록시 정보가 없습니다. 프록시 없이 진행합니다.")
    threading.Thread(target=crawl_worker, args=(url, sp, ep, proxy_var.get()), daemon=True).start()


btns = ctk.CTkFrame(ct, fg_color="transparent")
btns.pack(fill="x", padx=10, pady=(0, 10))
ctk.CTkButton(btns, text="크롤링 시작", fg_color=GREEN, hover_color=GREEN_D, command=start_crawl).pack(side="left", padx=4)
ctk.CTkButton(btns, text="중단", fg_color="#ef4444", hover_color="#dc2626",
              command=lambda: crawl_state.update(running=False)).pack(side="left", padx=4)
ctk.CTkButton(btns, text="엑셀 저장", fg_color="#374151", hover_color="#1f2937", command=save_excel).pack(side="left", padx=4)

# ── 설정 탭 ──
st = tabs.tab("설정")
ctk.CTkLabel(st, text="API 키 / BrightData 설정 (저장하면 config.json에 보관)",
             font=("맑은 고딕", 13, "bold")).pack(anchor="w", padx=16, pady=(16, 8))

FIELDS = [
    ("gemini_key", "Gemini API 키 (릴스 대사 추출)"),
    ("apify_token", "Apify 토큰 (선택 — 안 쓰면 비워둠)"),
    ("brightdata_proxy_user", "BrightData 프록시 Username"),
    ("brightdata_proxy_pass", "BrightData 프록시 Password"),
    ("brightdata_unlocker_key", "BrightData Web Unlocker API 키"),
    ("brightdata_unlocker_zone", "Web Unlocker Zone (기본 web_unlocker2)"),
]
entries = {}
for key, label in FIELDS:
    row = ctk.CTkFrame(st, fg_color="transparent")
    row.pack(fill="x", padx=16, pady=4)
    ctk.CTkLabel(row, text=label, width=280, anchor="w", font=FONT).pack(side="left")
    show = "" if "pass" in key or "key" in key else None
    e = ctk.CTkEntry(row, width=380, show=("•" if ("pass" in key or "key" in key) else ""))
    e.insert(0, CONFIG.get(key, ""))
    e.pack(side="left", padx=8)
    entries[key] = e


def do_save():
    for k, e in entries.items():
        CONFIG[k] = e.get().strip()
    save_config(CONFIG)
    messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")


ctk.CTkButton(st, text="설정 저장", fg_color=GREEN, hover_color=GREEN_D, command=do_save).pack(anchor="w", padx=16, pady=16)

app.mainloop()
