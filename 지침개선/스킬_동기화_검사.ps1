param(
    [switch]$Sync
)

$ErrorActionPreference = 'Stop'
$guidelineRoot = 'C:\Users\1\Desktop\지침'
$installedRoot = Join-Path $env:USERPROFILE '.codex\skills'
$validator = Join-Path $env:USERPROFILE '.codex\skills\.system\skill-creator\scripts\quick_validate.py'

$channels = @(
    @{
        Name = '화 가나다'
        Skill = 'hwa-ganada'
        Folder = Join-Path $guidelineRoot '1. 화가난다'
        References = @{
            '화가나다_프로젝트_지침_V3.3_통합본.md' = 'references\project-guidelines-v3.3.md'
            '화가나다_Gold_Standard_Reference_01.md' = 'references\gold-standard-reference-01.md'
            '컷분해지침_824eac49.md' = 'references\cut-guidelines.md'
        }
    },
    @{
        Name = '18점'
        Skill = 'channel-18jeom'
        Folder = Join-Path $guidelineRoot '2. 18점'
        References = @{
            '18점_EDITH_쇼핑쇼츠_마스터_V7.8.md' = 'references\master-v7.8.md'
            '18점_간식_레퍼런스_대본_DB.md' = 'references\reference-script-db.md'
            '컷분해지침_824eac49.md' = 'references\cut-guidelines.md'
        }
    },
    @{
        Name = '랜드마커'
        Skill = 'landmarker'
        Folder = Join-Path $guidelineRoot '3. 랜드마커'
        References = @{
            '랜드마커_프로젝트지침_V1.4.md' = 'references\base-v1.4.md'
            '랜드마커_지침_V1.5_추가교체조항.md' = 'references\v1.5-overrides.md'
            '랜드마커_자사정답_대본.md' = 'references\house-gold-scripts.md'
            '랜드마커_벤치마크_6편.md' = 'references\benchmark-6.md'
            '컷분해지침_824eac49.md' = 'references\cut-guidelines.md'
        }
    }
)

function Get-NormalizedText([string]$Path) {
    return ((Get-Content -Raw -LiteralPath $Path) -replace "`r`n", "`n").TrimEnd()
}

$problems = [System.Collections.Generic.List[string]]::new()

foreach ($channel in $channels) {
    $sourceSkill = Join-Path $channel.Folder ('개인스킬\' + $channel.Skill)
    $installedSkill = Join-Path $installedRoot $channel.Skill

    foreach ($entry in $channel.References.GetEnumerator()) {
        $canonical = Join-Path $channel.Folder $entry.Key
        $skillReference = Join-Path $sourceSkill $entry.Value

        if ($Sync) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $skillReference) | Out-Null
            Copy-Item -LiteralPath $canonical -Destination $skillReference -Force
        }

        if (-not (Test-Path -LiteralPath $canonical) -or -not (Test-Path -LiteralPath $skillReference)) {
            $problems.Add("$($channel.Name): 기준 파일 또는 스킬 참고자료 누락 — $($entry.Key)")
        }
        elseif ((Get-NormalizedText $canonical) -ne (Get-NormalizedText $skillReference)) {
            $problems.Add("$($channel.Name): 기준 파일과 스킬 참고자료 불일치 — $($entry.Key)")
        }
    }

    if ($Sync) {
        Get-ChildItem -LiteralPath $sourceSkill -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($sourceSkill.Length).TrimStart('\')
            $destination = Join-Path $installedSkill $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
        }
    }

    if (-not (Test-Path -LiteralPath $installedSkill)) {
        $problems.Add("$($channel.Name): 설치된 개인 스킬이 없음")
    }
    else {
        Get-ChildItem -LiteralPath $sourceSkill -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($sourceSkill.Length).TrimStart('\')
            $installedFile = Join-Path $installedSkill $relative
            if (-not (Test-Path -LiteralPath $installedFile)) {
                $problems.Add("$($channel.Name): 설치본 파일 누락 — $relative")
            }
            elseif ((Get-NormalizedText $_.FullName) -ne (Get-NormalizedText $installedFile)) {
                $problems.Add("$($channel.Name): 편집용 원본과 설치본 불일치 — $relative")
            }
        }
    }

    & python -X utf8 $validator $sourceSkill
    if (Test-Path -LiteralPath $installedSkill) {
        & python -X utf8 $validator $installedSkill
    }
}

if ($problems.Count -gt 0) {
    $problems | ForEach-Object { Write-Host "문제: $_" -ForegroundColor Red }
    exit 1
}

if ($Sync) {
    Write-Host '동기화와 검사가 모두 완료됐습니다.' -ForegroundColor Green
}
else {
    Write-Host '세 채널의 기준 파일·편집용 스킬·설치본이 모두 일치합니다.' -ForegroundColor Green
}

