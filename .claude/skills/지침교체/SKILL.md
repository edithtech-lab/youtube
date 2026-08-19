---
name: 지침교체
description: 현행 지침 해시 확인 → 지침/ 에 md 뽑기 → claude.ai 프로젝트 지식 교체 안내
---

# 지침 교체 절차

컷 분해는 앱 밖(claude.ai)에서 돈다. **지침을 고쳐도 앱 빌드로는 반영되지 않는다** —
사용자가 claude.ai 프로젝트 지식을 직접 교체해야 한다.

1. 현행 지침을 파일로 뽑는다 (앱의 [📋 지침 복사]와 같은 원문):
   ```
   python -c "
   import sys, io, re
   sys.stdout.reconfigure(encoding='utf-8', errors='replace')
   import main as M
   t = M.Api().split_guide()['text']
   ver = re.search(r'지침 버전 ([0-9a-f]{8})', t).group(1)
   io.open(r'지침/컷분해지침_%s.md' % ver, 'w', encoding='utf-8').write(t)
   print(ver)"
   ```
   (프로젝트 루트에서. 해시는 내용 sha1 앞 8자리 — 내용이 같으면 번호도 같다.)

2. `지침/` 에는 **최신 하나만** 둔다. 이전 판이 있으면 `지침/_옛판/` 으로 옮긴다.
   최신이 둘 이상 굴러다니면 옛 판을 올리는 사고가 난다.

3. 사용자 안내:
   - claude.ai 프로젝트 지식에서 옛 지침 삭제 → 새 파일 업로드
   - 첫 줄의 8자리 번호가 방금 뽑은 해시와 같은지 대조
   - 교체 전까지는 컷 분해가 옛 규칙으로 나온다는 점을 알린다
