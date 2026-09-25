# 나머지 리뷰 전체 분류(5,224건 중 데모 989건 제외) → FAQ 답변 갱신
#   1단계: 나머지 10개 상품의 인접 마지막 두 달(2,509건, 약 43시간) — 모든 상품의 두 달 비교 확보
#   2단계: 14개 상품의 첫 달(1,726건, 약 30시간) — 3개월 흐름 완성, 시간이 부족하면 중단 가능
#   마지막: 14개 상품 FAQ 답변 생성·갱신(최신 답은 건너뜀)
# 데모 배치와 그 후속 작업(after_demo_batch.ps1)이 끝난 뒤 시작합니다. 중단 후 다시 실행하면 이어서 처리합니다.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# === [대기] 먼저 걸린 분류·FAQ 작업이 모두 끝날 때까지 1분마다 확인 ===
Write-Output "=== $(Get-Date -Format s) waiting for demo batch and after_demo_batch ==="
while (Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match "run_demo_batch|after_demo_batch|scripts.classify_reviews|scripts.generate_faq_answers" -and
        $_.CommandLine -notmatch "run_remaining_batch"
    }) {
    Start-Sleep -Seconds 60
}

function Invoke-Classify($id, $months, $label) {
    Write-Output "=== $(Get-Date -Format s) [$label] start $id $($months -join ',') ==="
    $monthArgs = @()
    foreach ($month in $months) { $monthArgs += @("--month", $month) }
    & .\.venv\Scripts\python.exe -m scripts.classify_reviews `
        --run-id amazon-absa-qwen35-v3 --product-id $id @monthArgs `
        --max-attempts 2 --timeout 180 --activate `
        --output "data/evaluation/full_$id"
    Write-Output "=== $(Get-Date -Format s) [$label] end $id exit=$LASTEXITCODE ==="
}

# === [1단계] 나머지 10개 상품의 인접 마지막 두 달 ===
$phase1 = @(
    @{ id = "amazon-B09M8N7YML"; months = @("2022-08", "2022-09") },  # 알로 보안 카메라
    @{ id = "amazon-B000FS05VG"; months = @("2015-07", "2015-08") },  # 레브론 드라이어
    @{ id = "amazon-B08YGYBQTZ"; months = @("2015-02", "2015-03") },  # 도루코 면도기
    @{ id = "amazon-B08DQGH9T1"; months = @("2021-07", "2021-08") },  # 슈피겐 보호필름
    @{ id = "amazon-B0CFTCTHTK"; months = @("2021-11", "2021-12") },  # 커피머신 석회 제거제
    @{ id = "amazon-B07FC9NRRR"; months = @("2020-10", "2020-11") },  # 자전거 조명
    @{ id = "amazon-B0764PP6R8"; months = @("2017-01", "2017-02") },  # 스태빌리티 볼
    @{ id = "amazon-B00HT5HBMO"; months = @("2021-05", "2021-06") },  # 녹음 버저
    @{ id = "amazon-B01EX2IAZM"; months = @("2021-02", "2021-03") },  # 화장지
    @{ id = "amazon-B0B7LC848X"; months = @("2021-06", "2021-07") }   # 세탁세제 시트
)
foreach ($item in $phase1) { Invoke-Classify $item.id $item.months "phase1" }

# === [2단계] 14개 상품의 첫 달 ===
$phase2 = @(
    @{ id = "amazon-B087H2LWWZ"; month = "2021-12" },
    @{ id = "amazon-B08VD2NX25"; month = "2022-02" },
    @{ id = "amazon-B07NZJ1MHX"; month = "2020-10" },
    @{ id = "amazon-B0BWLH7QX5"; month = "2022-11" },
    @{ id = "amazon-B09M8N7YML"; month = "2022-07" },
    @{ id = "amazon-B000FS05VG"; month = "2015-06" },
    @{ id = "amazon-B08YGYBQTZ"; month = "2015-01" },
    @{ id = "amazon-B08DQGH9T1"; month = "2021-06" },
    @{ id = "amazon-B0CFTCTHTK"; month = "2021-10" },
    @{ id = "amazon-B07FC9NRRR"; month = "2020-09" },
    @{ id = "amazon-B0764PP6R8"; month = "2016-12" },
    @{ id = "amazon-B00HT5HBMO"; month = "2021-04" },
    @{ id = "amazon-B01EX2IAZM"; month = "2021-01" },
    @{ id = "amazon-B0B7LC848X"; month = "2021-05" }
)
foreach ($item in $phase2) { Invoke-Classify $item.id @($item.month) "phase2" }

# === [마지막] 14개 상품 FAQ 답변 생성·갱신 ===
Write-Output "=== $(Get-Date -Format s) generate FAQ answers for all products ==="
& .\.venv\Scripts\python.exe -m scripts.generate_faq_answers --all
Write-Output "=== $(Get-Date -Format s) all done ==="
