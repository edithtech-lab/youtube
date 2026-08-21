# -*- coding: utf-8 -*-
"""배포 폴더 → zip → GitHub 릴리스 자산 업로드.

**왜 저장소에 두는가**: 2026-08-21 부터 `배포본_만들기.ps1` 이 재빌드 후 사용자의
`config.json`(평문 API 키)을 배포 폴더에 되돌려 놓는다. 그 전에는 빌드 직후 폴더가
항상 깨끗해서 "어쩌다 안전"했지만 이제는 아니다. 그래서 zip 을 만드는 길이 **반드시**
이 스크립트 하나로 고정돼야 한다 — 매번 임시 스크립트를 새로 쓰면 검사가 빠진다.

안전장치 두 겹:
  ① 담을 때  — 앱 루트의 config*.json · .env · *.key 를 건너뛴다
  ② 담은 뒤  — 만든 zip 을 다시 열어 그 파일들이 없는지 assert 로 확인
  (_internal 안의 config.v1.json 류는 구글 discovery 문서라 키와 무관하고 런타임에 필요하다
   — 그래서 '앱 루트'만 본다)

토큰은 git credential helper 에서 실행 시점에 꺼내 쓴다 (파일에 적지 않는다).

사용: python 릴리스_올리기.py v0.5 "릴리스 제목" 본문.txt
"""
import os
import sys
import subprocess
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "edithtech-lab/youtube"
SRC = os.path.join(os.path.expanduser("~"), "Desktop", "통합수집기_배포")
PROJ = os.path.dirname(os.path.abspath(__file__))


def _is_secret(rel_path, name):
    """앱 루트에 있는 비밀 파일인가. 하위 폴더는 라이브러리 몫이라 건드리지 않는다."""
    if os.sep in rel_path:
        return False
    n = name.lower()
    return (n.startswith("config") and n.endswith(".json")) or n == ".env" or n.endswith(".key")


def make_zip(zip_path):
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(SRC):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), SRC)
                if _is_secret(rel, f):
                    print("   제외:", rel)
                    continue
                z.write(os.path.join(root, f), rel)
    # ② 만든 결과물을 다시 열어 확인한다 — 담을 때의 조건문이 틀렸어도 여기서 걸린다
    with zipfile.ZipFile(zip_path) as z:
        bad = [n for n in z.namelist() if _is_secret(n.replace("/", os.sep), n.split("/")[-1])
               and "/" not in n]
    if bad:
        os.remove(zip_path)
        raise SystemExit("❌ zip 에 비밀 파일이 들어갔습니다 — 삭제했습니다: %s" % bad)
    print("zip %.0fMB · 비밀 파일 미포함 검증 ✅" % (os.path.getsize(zip_path) / 1e6))


def token():
    cred = subprocess.run(["git", "credential", "fill"], cwd=PROJ, capture_output=True, text=True,
                          input="protocol=https\nhost=github.com\nusername=edithtech-lab\n\n")
    tok = dict(l.split("=", 1) for l in cred.stdout.strip().splitlines()
               if "=" in l).get("password", "")
    if not tok:
        raise SystemExit("❌ GitHub 토큰을 못 꺼냈습니다 (git credential)")
    return tok


def main():
    if len(sys.argv) < 3:
        raise SystemExit("사용: python 릴리스_올리기.py <태그> <제목> [본문파일]")
    tag, title = sys.argv[1], sys.argv[2]
    body = ""
    if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
        body = open(sys.argv[3], encoding="utf-8").read()
    if not os.path.isdir(SRC):
        raise SystemExit("❌ 배포 폴더가 없습니다: %s (먼저 배포본_만들기.ps1)" % SRC)

    import requests
    zip_path = os.path.join("D:\\", "통합수집기_%s.zip" % tag)
    print("zip 생성 중…")
    make_zip(zip_path)

    h = {"Authorization": "Bearer " + token(), "Accept": "application/vnd.github+json"}
    asset = "collector_%s_win64.zip" % tag
    r = requests.get("https://api.github.com/repos/%s/releases/tags/%s" % (REPO, tag),
                     headers=h, timeout=30)
    if r.status_code == 200:
        rel = r.json()
        print("기존 릴리스 재사용:", rel["id"])
    else:
        r = requests.post("https://api.github.com/repos/%s/releases" % REPO, headers=h, timeout=30,
                          json={"tag_name": tag, "name": title,
                                "target_commitish": "main", "body": body})
        if r.status_code != 201:
            raise SystemExit("❌ 릴리스 생성 실패: %s %s" % (r.status_code, r.text[:300]))
        rel = r.json()
        print("릴리스 생성:", rel["id"])
    for a in rel.get("assets", []):
        if a["name"] == asset:
            requests.delete(a["url"], headers=h, timeout=30)
            print("기존 자산 삭제")
    print("업로드 시작: %.0fMB" % (os.path.getsize(zip_path) / 1e6))
    with open(zip_path, "rb") as f:
        up = requests.post("https://uploads.github.com/repos/%s/releases/%s/assets?name=%s"
                           % (REPO, rel["id"], asset),
                           headers={**h, "Content-Type": "application/zip"}, data=f, timeout=3600)
    if up.status_code != 201:
        raise SystemExit("❌ 업로드 실패: %s %s" % (up.status_code, up.text[:300]))
    print("✅ 완료: https://github.com/%s/releases/tag/%s" % (REPO, tag))


if __name__ == "__main__":
    main()
