# 데모 분류 배치(run_demo_batch.ps1)가 끝나면 이어서 실행합니다.
#   1) 실패 리뷰 재분류(--retry-failed)  2) 데모 4개 상품 FAQ 답변 미리 생성
# 분류와 FAQ 생성을 동시에 돌리면 둘 다 느려지므로 순서대로 실행합니다.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# === [대기] 분류 배치 프로세스가 끝날 때까지 1분마다 확인 ===
Write-Output "=== $(Get-Date -Format s) waiting for run_demo_batch ==="
while (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "run_demo_batch|scripts.classify_reviews" -and $_.ProcessId -ne $PID }) {
    Start-Sleep -Seconds 60
}

# === [1] 실패 리뷰 재분류 ===
$items = @(
    @{ id = "amazon-B087H2LWWZ"; months = @("2022-01", "2022-02") },
    @{ id = "amazon-B08VD2NX25"; months = @("2022-03", "2022-04") },
    @{ id = "amazon-B07NZJ1MHX"; months = @("2020-11", "2020-12") },
    @{ id = "amazon-B0BWLH7QX5"; months = @("2022-12", "2023-01") }
)
foreach ($item in $items) {
    Write-Output "=== $(Get-Date -Format s) retry failed $($item.id) ==="
    & .\.venv\Scripts\python.exe -m scripts.classify_reviews `
        --run-id amazon-absa-qwen35-v3 --product-id $item.id `
        --month $item.months[0] --month $item.months[1] `
        --retry-failed --max-attempts 2 --timeout 180 --activate `
        --output "data/evaluation/demo_$($item.id)"
}

# === [2] FAQ 답변 미리 생성(최신 분석 기준) ===
Write-Output "=== $(Get-Date -Format s) generate FAQ answers ==="
& .\.venv\Scripts\python.exe -m scripts.generate_faq_answers --demo
Write-Output "=== $(Get-Date -Format s) all done ==="
