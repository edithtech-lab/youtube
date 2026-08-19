# 남에게 줄 배포본을 만든다. 원본 폴더는 건드리지 않는다.
#
#   .\배포본_만들기.ps1            소스가 exe 보다 새것이면 자동으로 다시 빌드한 뒤 배포
#   .\배포본_만들기.ps1 -Force     최신이어도 무조건 다시 빌드
#   .\배포본_만들기.ps1 -NoBuild   빌드 없이 현재 exe 로만 배포 (예전 동작)
#
# 왜 빌드까지 하는가 (2026-08-12 추가):
#   예전엔 이 스크립트가 collector.exe 를 **복사만** 했다. 그래서 main.py 를 고치고 이걸
#   돌리면 "UI 는 새것, exe 는 옛것"인 배포본이 조용히 만들어졌다 — 오류가 안 나서
#   알아채기 어렵다. 게다가 이 프로젝트는 **파이썬 3.13** 으로 빌드해야 하는데 `python`
#   명령은 3.10 을 가리켜서, 무심코 빌드하면 exe 와 _internal 의 파이썬이 어긋나 앱이
#   아예 안 뜬다 (2026-08-12 실제로 겪음). 두 함정 모두 여기서 막는다.
#
# 빠지는 것 (의도적):
#   제작파일\      채널 지침·레퍼런스 md — 노출 금지
#   config.json    API 키가 평문으로 들어 있다
#   *.py, ui\      소스
#   다운로더\, _internal_백업, dist, build, 로그, 구버전 exe

param(
    [switch]$Force,     # 최신이어도 무조건 재빌드
    [switch]$NoBuild    # 빌드 건너뛰기
)

$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = Join-Path ([Environment]::GetFolderPath("Desktop")) "통합수집기_배포"
$exe = Join-Path $src "collector.exe"

# ── 이 프로젝트가 요구하는 파이썬 판을 _internal 에서 읽는다 ──────────────
# 현재 _internal 안의 pythonNNN.dll 이 곧 "이 exe 가 물고 있는 런타임"이다.
# 이것과 다른 판으로 빌드하면 exe 와 _internal 이 어긋나 앱이 안 뜬다.
# ⚠ -Filter 에 "python3??.dll" 을 쓰면 안 된다 — 윈도우 레거시 와일드카드에서 ? 가 0글자에도
#   매칭돼 판 정보가 없는 python3.dll 이 먼저 잡힌다 (2026-08-12 실측). 정규식으로 거른다.
function Get-PyDll($dir) {
    Get-ChildItem $dir -Filter "python*.dll" -EA SilentlyContinue |
        Where-Object { $_.Name -match '^python3\d+\.dll$' } | Select-Object -First 1
}

function Get-RequiredPy {
    $dll = Get-PyDll (Join-Path $src "_internal")
    if ($dll -and $dll.Name -match '^python3(\d+)\.dll$') { return "3.$($Matches[1])" }
    return $null
}

# ── 소스가 exe 보다 새것인가 ────────────────────────────────────────────
function Test-SourceNewer {
    if (-not (Test-Path $exe)) { return $true }
    $t = (Get-Item $exe).LastWriteTime
    $watch = @("main.py", "studio.py", "collector.spec") | ForEach-Object { Join-Path $src $_ }
    $watch += (Get-ChildItem (Join-Path $src "ui") -Recurse -File -EA SilentlyContinue).FullName
    foreach ($f in $watch) {
        if ((Test-Path $f) -and (Get-Item $f).LastWriteTime -gt $t) { return $true }
    }
    return $false
}

# ── ① 빌드 ─────────────────────────────────────────────────────────────
if ($NoBuild) {
    Write-Host "[빌드] 건너뜀 (-NoBuild) — 현재 exe 로 배포합니다" -ForegroundColor Yellow
}
elseif (-not $Force -and -not (Test-SourceNewer)) {
    Write-Host "[빌드] 소스가 exe 보다 오래됨 — 다시 빌드할 필요 없음" -ForegroundColor DarkGray
}
else {
    $pyver = Get-RequiredPy
    if (-not $pyver) {
        throw "_internal 에서 파이썬 판을 못 찾았습니다. -NoBuild 로 돌리거나 _internal 을 확인하세요."
    }
    # 그 판이 실제로 깔려 있고 PyInstaller 도 있는지 먼저 확인 — 없으면 빌드를 시작조차 하지 않는다
    $probe = & py "-$pyver" -c "import PyInstaller,sys;print(sys.version.split()[0],PyInstaller.__version__)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "파이썬 $pyver 또는 PyInstaller 가 없습니다 ($probe). `py -$pyver -m pip install pyinstaller` 후 다시 시도하세요."
    }
    Write-Host "[빌드] 파이썬 $pyver 로 빌드합니다 ($probe)" -ForegroundColor Cyan

    # docs/_현황.md 갱신 — 톤·카메라·리빌·모델·단가·지침 번호를 main.py 에서 다시 뽑는다.
    # 손으로 적어둔 목록은 반드시 썩고, 썩은 목록은 없는 것보다 나쁘다(그걸 믿고 작업한다).
    # 빌드에 묶어두면 코드와 문서가 어긋날 수가 없다. 실패해도 빌드는 계속한다 — 문서 때문에
    # 배포가 막히면 안 된다.
    $gen = Join-Path $src "docs\_현황_뽑기.py"
    if (Test-Path $gen) {
        try {
            & py "-$pyver" $gen | Out-Null
            if ($LASTEXITCODE -eq 0) { Write-Host "        docs\_현황.md 갱신" }
            else { Write-Warning "docs\_현황.md 갱신 실패 (빌드는 계속합니다)" }
        } catch { Write-Warning "docs\_현황.md 갱신 실패: $_ (빌드는 계속합니다)" }
    }

    # 산출물은 여유가 가장 많은 드라이브에 만든다 — C: 가 꽉 차서 복사가 중간에 끊긴 적이 있다
    $best = Get-PSDrive -PSProvider FileSystem |
            Where-Object { $_.Free -gt 5GB -and $_.Name -match '^[A-Z]$' } |
            Sort-Object Free -Descending | Select-Object -First 1
    if (-not $best) { throw "빌드할 여유 공간(5GB 이상)이 있는 드라이브가 없습니다." }
    $work = Join-Path "$($best.Name):\" "_collector_build"
    Write-Host "        작업 폴더: $work (여유 $([math]::Round($best.Free/1GB))GB)"

    # ⚠ PyInstaller 는 진행 로그를 stderr 로 쏟는다. 위의 $ErrorActionPreference="Stop" 과 만나면
    #   PowerShell 5.1 이 그 로그 한 줄 한 줄을 치명적 오류(NativeCommandError)로 바꿔버려
    #   멀쩡한 빌드가 실패로 끝난다 (2026-08-12 실측). Start-Process 로 실행해 출력을 파일로
    #   받고 **종료코드로만** 성패를 판단한다 — 파이프/리다이렉션을 쓰면 같은 함정에 걸린다.
    New-Item -ItemType Directory -Force $work | Out-Null
    $log = Join-Path $work "build.log"
    $errLog = Join-Path $work "build.err.log"
    # $args 는 PowerShell 예약 변수라 다른 이름을 쓴다
    $piArgs = @("-$pyver", "-m", "PyInstaller", "collector.spec", "--noconfirm",
                "--distpath", (Join-Path $work "dist"), "--workpath", (Join-Path $work "build"))
    $proc = Start-Process -FilePath "py" -ArgumentList $piArgs -WorkingDirectory $src `
                          -NoNewWindow -Wait -PassThru `
                          -RedirectStandardOutput $log -RedirectStandardError $errLog
    if ($proc.ExitCode -ne 0) {
        Write-Host "`n--- 빌드 로그 끝부분 ---" -ForegroundColor Red
        Get-Content $errLog -Tail 15 -EA SilentlyContinue
        throw "PyInstaller 실패 (종료코드 $($proc.ExitCode)). 전체 로그: $errLog"
    }

    $out = Join-Path $work "dist\collector"
    if (-not (Test-Path (Join-Path $out "collector.exe"))) { throw "빌드 결과에 collector.exe 가 없습니다." }

    # 안전장치 — 만들어진 _internal 의 파이썬이 요구 판과 같은지 확인하고 나서야 덮어쓴다
    $newDll = Get-PyDll (Join-Path $out "_internal")
    $want = "python$($pyver.Replace('.',''))" + ".dll"
    if (-not $newDll -or $newDll.Name -ne $want) {
        throw "빌드된 파이썬이 다릅니다 (기대 $want / 실제 $(if($newDll){$newDll.Name}else{'없음'})). 덮어쓰지 않고 중단합니다."
    }

    Copy-Item (Join-Path $out "collector.exe") $exe -Force
    Copy-Item (Join-Path $out "_internal\*") (Join-Path $src "_internal") -Recurse -Force
    Remove-Item $work -Recurse -Force -EA SilentlyContinue
    Write-Host "[빌드] 완료 — exe 와 _internal 갱신" -ForegroundColor Green
}

# ── ② 배포본 복사 ──────────────────────────────────────────────────────
if (Test-Path $dst) {
    Write-Host "기존 배포 폴더를 지웁니다: $dst"
    Remove-Item $dst -Recurse -Force
}
New-Item -ItemType Directory -Force $dst | Out-Null

# 필수 — 이 둘만 있으면 실행된다
Copy-Item $exe $dst -Force
Copy-Item (Join-Path $src "_internal") $dst -Recurse -Force

# ── ③ 검사 ─────────────────────────────────────────────────────────────
# 번들 안에 소스나 지침이 섞여 들어갔는지 확인 (PyInstaller 설정이 바뀌면 생길 수 있다)
$leak = @()
$leak += Get-ChildItem $dst -Recurse -File -Include "*지침*.md", "프리셋.json" -EA SilentlyContinue
$leak += Get-ChildItem $dst -Recurse -File -Include "main.py", "studio.py", "config.json" -EA SilentlyContinue
$leak += Get-ChildItem (Join-Path $dst "_internal") -Directory -Filter "제작파일" -EA SilentlyContinue
if ($leak.Count -gt 0) {
    Write-Host "`n[경고] 배포본에 들어가면 안 되는 것이 섞였습니다 — 지우고 다시 확인하세요:" -ForegroundColor Red
    $leak | ForEach-Object { "   " + $_.FullName.Replace($dst, "") }
} else {
    Write-Host "`n지침·소스·API키 유출 없음 (확인 완료)" -ForegroundColor Green
}

# exe 와 _internal 의 파이썬이 맞는지 마지막으로 한 번 더 — 어긋나면 앱이 아예 안 뜬다
$dllOut = Get-PyDll (Join-Path $dst "_internal")
$dllName = if ($dllOut) { $dllOut.Name } else { "⚠ 파이썬 DLL 없음 — 실행 안 됩니다" }
Write-Host "런타임: $dllName / exe: $((Get-Item (Join-Path $dst 'collector.exe')).LastWriteTime)"

$mb = [math]::Round((Get-ChildItem $dst -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
$freeC = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Write-Host "`n배포본: $dst  ($mb MB)"
if ($freeC -lt 5) { Write-Host "[주의] C: 여유 공간이 ${freeC}GB 뿐입니다 — 정리를 권합니다" -ForegroundColor Yellow }
Write-Host "받는 사람은 앱을 켜고 [설정]에서 본인 API 키를 넣으면 됩니다."
Write-Host "대본 스튜디오 탭은 숨겨져 있고, 제작파일(지침)은 들어가지 않습니다."
