# finish_all.ps1 — 남은 수집 작업을 순차 완주하고 커밋·푸시 후 PC 종료
#
# 순서: (1) 단지정보 수집 완료 대기 → 검증·커밋 → (2) 공급면적 수집 → 검증·커밋 → (3) 종료
#
# 안전장치:
#  - JSON 파싱 + 최소 건수 검증을 통과할 때만 커밋 (실패해도 다음 단계는 계속)
#  - 종료는 300초 지연 → 취소하려면:  shutdown /a
#  - 모든 출력은 finish_all.log 에 기록
#
# 실행: powershell -ExecutionPolicy Bypass -File finish_all.ps1

$ErrorActionPreference = 'Continue'
$repo = 'C:\CLI\PROJECT\부동산'
$log  = Join-Path $repo 'finish_all.log'
Set-Location $repo

function Say($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    $line | Tee-Object -FilePath $log -Append
}

# JSON이 유효하고 최소 건수 이상일 때만 커밋·푸시
function CommitIfValid($file, $minCount, $message) {
    $path = Join-Path $repo $file
    if (-not (Test-Path $path)) { Say "SKIP: $file 없음"; return }
    try {
        $obj = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $n = ($obj.PSObject.Properties | Measure-Object).Count
    } catch { Say "SKIP: $file JSON 파싱 실패"; return }
    if ($n -lt $minCount) { Say "SKIP: $file 항목 $n 개 (최소 $minCount 미달)"; return }
    Say "$file 검증 통과 — $n 개 항목, 커밋합니다"
    git add $file 2>&1 | Out-Null
    git add data/kapt_cache data/hspms_cache 2>&1 | Out-Null
    git commit -m $message 2>&1 | Select-Object -Last 1 | ForEach-Object { Say $_ }
    git push origin master 2>&1 | Select-Object -Last 1 | ForEach-Object { Say $_ }
}

Say '=== 자동 완주 시작 ==='

# 1) 실행 중인 단지정보 수집(apt_info.py) 완료 대기
Say '1단계: 단지정보(세대수·주차대수) 수집 완료 대기'
while ($true) {
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
               Where-Object { $_.CommandLine -match 'apt_info\.py' }
    if (-not $running) { break }
    Start-Sleep -Seconds 60
}
Say '1단계 완료'
CommitIfValid 'data/apt_info.json' 500 @'
Data: 공동주택 단지정보(세대수·주차대수) 수집 반영

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@

# 2) 공급면적 수집
Say '2단계: 공급면적(전유+주거공용) 수집 시작'
python -X utf8 supply_area.py 2>&1 | Tee-Object -FilePath $log -Append
Say '2단계 완료'
CommitIfValid 'data/supply_area.json' 500 @'
Data: 주택인허가 기반 아파트 공급면적 테이블 생성

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@

# 3) 최종 안전망: 남은 변경 전부 커밋 + 푸시 (종료 전 미푸시 상태를 남기지 않는다)
Say '3단계: 남은 변경 최종 커밋·푸시'
$dirty = git status --porcelain 2>&1
if ($dirty) {
    Say ("미커밋 변경 {0}건 — 커밋합니다" -f ($dirty | Measure-Object).Count)
    git add -A 2>&1 | Out-Null
    git commit -m @'
Data: 수집 마무리 - 남은 변경 반영

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@ 2>&1 | Select-Object -Last 1 | ForEach-Object { Say $_ }
} else {
    Say '미커밋 변경 없음'
}

# 푸시는 항상 시도 (앞 단계에서 커밋만 되고 푸시가 실패했을 수 있음)
for ($i = 1; $i -le 3; $i++) {
    $r = git push origin master 2>&1
    $r | Select-Object -Last 1 | ForEach-Object { Say $_ }
    $ahead = git status -sb 2>&1 | Select-String 'ahead'
    if (-not $ahead) { Say '푸시 확인 완료 — 원격과 동기화됨'; break }
    Say ("푸시 미완료 — 재시도 {0}/3" -f $i)
    Start-Sleep -Seconds 20
}

$ahead = git status -sb 2>&1 | Select-String 'ahead'
if ($ahead) {
    Say '!!! 푸시 실패 — 종료를 취소합니다. 수동으로 git push 후 확인하세요'
    exit 1
}

# 4) 종료 (취소: shutdown /a)
Say '=== 전체 완료 + 푸시 확인 — 300초 후 PC를 종료합니다 (취소: shutdown /a) ==='
shutdown /s /t 300 /c "부동산 데이터 수집 완료 - 자동 종료 (취소: shutdown /a)"
