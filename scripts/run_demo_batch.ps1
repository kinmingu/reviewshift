# 데모 4개 상품 × 인접 두 달(989건) v3 분류 배치 (README "데모 분류 범위" 참고)
# 중단 후 다시 실행하면 성공 건은 건너뛰고 이어서 처리합니다.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$items = @(
    @{ id = "amazon-B087H2LWWZ"; months = @("2022-01", "2022-02") },
    @{ id = "amazon-B08VD2NX25"; months = @("2022-03", "2022-04") },
    @{ id = "amazon-B07NZJ1MHX"; months = @("2020-11", "2020-12") },
    @{ id = "amazon-B0BWLH7QX5"; months = @("2022-12", "2023-01") }
)

foreach ($item in $items) {
    Write-Output "=== $(Get-Date -Format s) start $($item.id) $($item.months -join ',') ==="
    & .\.venv\Scripts\python.exe -m scripts.classify_reviews `
        --run-id amazon-absa-qwen35-v3 --product-id $item.id `
        --month $item.months[0] --month $item.months[1] `
        --max-attempts 2 --timeout 180 --activate `
        --output "data/evaluation/demo_$($item.id)"
    Write-Output "=== $(Get-Date -Format s) end $($item.id) exit=$LASTEXITCODE ==="
}
Write-Output "=== $(Get-Date -Format s) all done ==="
