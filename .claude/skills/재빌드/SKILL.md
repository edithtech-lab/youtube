---
name: 재빌드
description: 앱 종료 확인 → 회귀 검사 → 배포본_만들기.ps1 -Force → 결과·유출 검사 확인
---

# 재빌드 절차

1. **앱이 켜져 있으면 빌드가 실패한다.** 먼저 확인:
   ```powershell
   Get-Process -Name collector -ErrorAction SilentlyContinue
   ```
   떠 있으면 사용자에게 닫아달라고 요청 (강제 종료하지 말 것 — 작업 중일 수 있다).

2. **프롬프트 문구를 고친 빌드라면** 회귀 검사 먼저:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tests\전체검사.ps1
   ```
   실패 항목이 있으면 빌드하지 말고 원인부터.

3. 빌드 (5~10분 — 백그라운드 실행 권장):
   ```powershell
   .\배포본_만들기.ps1 -Force
   ```
   - 파이썬 **3.13** 은 스크립트가 알아서 고른다. 직접 pyinstaller 를 부르지 마라.
   - `docs/_현황_뽑기.py` 도 스크립트가 알아서 돌린다.

4. 출력에서 확인할 것:
   - `지침·소스·API키 유출 없음 (확인 완료)` 줄이 있는가 (절대 규칙 2)
   - exe 타임스탬프가 방금인가
   - C: 여유 공간 경고가 떴으면 사용자에게 전달

5. 강조 도구를 만들거나 고친 빌드라면 `python docs/_강조도구_뽑기.py` 로 `docs/06` 갱신.

6. **지침(SCENE_SPLIT_PROMPT)을 고친 빌드라면 빌드로는 반영 안 된다** — `/지침교체` 안내.
