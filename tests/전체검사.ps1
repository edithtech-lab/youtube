# 전체 회귀 검사 — 프롬프트 문구를 고친 뒤에는 이걸 돌려라.
# 실행: powershell -ExecutionPolicy Bypass -File tests\전체검사.ps1
$ErrorActionPreference = "Continue"
# 콘솔이 cp949 면 파이썬의 UTF-8 출력("전 항목 통과")이 깨져 통과 판정 자체가 실패한다
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$fail = 0

Write-Host "`n=== main.py 문법" -ForegroundColor Cyan
py -c "import py_compile; py_compile.compile(r'$root\main.py', doraise=True); print('  OK  컴파일 통과')"
if (-not $?) { $fail++ }

Write-Host "`n=== 파이썬 검사" -ForegroundColor Cyan
Get-ChildItem "$root\tests\*.py" | ForEach-Object {
    $out = & py $_.FullName 2>$null
    $last = $out | Select-Object -Last 1
    if ($last -match "통과") { Write-Host "  OK  $($_.BaseName)" }
    else { Write-Host "  실패 $($_.BaseName) : $last" -ForegroundColor Red; $out; $fail++ }
}

Write-Host "`n=== UI 정합성" -ForegroundColor Cyan
if (Get-Command node -ErrorAction SilentlyContinue) {
    node "$root\tests\ui_check.js"
    if (-not $?) { $fail++ }
    node "$root\tests\ui_scope.js"
    if (-not $?) { $fail++ }
} else {
    Write-Host "  건너뜀 — node 가 없습니다 (UI 문법·톤 목록 검사 불가)" -ForegroundColor Yellow
}

if ($fail) { Write-Host "`n$fail 건 실패" -ForegroundColor Red; exit 1 }
Write-Host "`n전 항목 통과" -ForegroundColor Green
