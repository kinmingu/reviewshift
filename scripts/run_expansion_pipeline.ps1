# 35개 상품 확장 후 전체 자동 실행(컴퓨터를 켜 두면 순서대로 진행)
#   1) 새 리뷰 검색용 임베딩(bge-m3, 약 1시간)
#   2) 상품별 AI 분석 표본 분류(20→30→50→70→100건 단계, 약 32시간)
#   3) 35개 상품 FAQ 답변 생성(약 4~5시간)
# 중단 후 다시 실행하면 끝난 작업은 건너뛰고 이어서 처리합니다.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Output "=== $(Get-Date -Format s) [1/3] embeddings ==="
& .\.venv\Scripts\python.exe -m scripts.embed_reviews --all
Write-Output "=== $(Get-Date -Format s) [2/3] sample classification ==="
& .\.venv\Scripts\python.exe -m scripts.run_sample_batch
Write-Output "=== $(Get-Date -Format s) [3/3] FAQ answers ==="
& .\.venv\Scripts\python.exe -m scripts.generate_faq_answers --all
Write-Output "=== $(Get-Date -Format s) all done ==="
