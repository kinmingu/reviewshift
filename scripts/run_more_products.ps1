# 카테고리별 상품 추가분(선정 파일에 추가된 상품) 적재 → 임베딩 → 표본 분류 → FAQ 생성
# 이미 적재·분류·생성된 부분은 모두 건너뛰므로 중단 후 다시 실행하면 이어서 처리합니다.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

foreach ($cat in "Electronics", "Beauty_and_Personal_Care", "Cell_Phones_and_Accessories", "Home_and_Kitchen", "Sports_and_Outdoors", "Toys_and_Games", "Health_and_Household") {
    Write-Output "=== $(Get-Date -Format s) [0/3] import $cat ==="
    & .\.venv\Scripts\python.exe -m scripts.import_amazon_category --category $cat 2>&1 |
        Select-String -Pattern '"reviews_inserted"|Error|Traceback' | ForEach-Object { $_.Line }
}
Write-Output "=== $(Get-Date -Format s) [1/3] embeddings ==="
& .\.venv\Scripts\python.exe -m scripts.embed_reviews --all
Write-Output "=== $(Get-Date -Format s) [2/3] sample classification ==="
& .\.venv\Scripts\python.exe -m scripts.run_sample_batch
Write-Output "=== $(Get-Date -Format s) [3/3] FAQ answers ==="
& .\.venv\Scripts\python.exe -m scripts.generate_faq_answers --all
& .\.venv\Scripts\python.exe -m scripts.export_product_list
Write-Output "=== $(Get-Date -Format s) all done ==="
