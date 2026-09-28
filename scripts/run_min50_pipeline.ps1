# 최소 표본 50건 확대(15/20/30건 → 50건, 35개 상품) 자동 실행
#   1) 늘어난 표본 AI 분석(약 1,000건, 약 10시간)  2) 낡은 FAQ 답변 다시 생성(약 7시간)  3) 상품 목록 갱신
# 실행 중에는 절전을 막고, 분석 완료·전체 완료·오류 때 Windows 알림을 띄웁니다.
# 끝난 작업은 건너뛰므로 중단 후 다시 실행하면 이어서 처리합니다.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8  # 로그의 한글이 깨지지 않게
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# === [절전 방지] 이 스크립트가 도는 동안만 시스템 절전을 막습니다 ===
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[Win32.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

# === [알림] Windows 기본 토스트(추가 설치 없음) ===
function Show-Toast([string]$title, [string]$body) {
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $safeTitle = [Security.SecurityElement]::Escape($title)
        $safeBody = [Security.SecurityElement]::Escape($body)
        $xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>$safeTitle</text><text>$safeBody</text></binding></visual><actions><action content='확인' arguments='ok'/></actions></toast>")
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show(
            [Windows.UI.Notifications.ToastNotification]::new($xml))
    } catch {
        Write-Output "toast failed: $_"
    }
}

Write-Output "=== $(Get-Date -Format s) [1/3] sample classification (min 50) ==="
& .\.venv\Scripts\python.exe -m scripts.run_sample_batch
if ($LASTEXITCODE -ne 0) {
    Show-Toast "ReviewShift: 표본 분석이 멈췄어요" "로그(data\evaluation\min50_pipeline.log)를 확인해 주세요. 다시 실행하면 이어서 처리합니다."
    exit 1
}
Show-Toast "ReviewShift: 표본 50건 분석 완료" "모든 상품이 분석 리뷰 50건 이상이 됐어요. 이어서 FAQ 답변을 다시 만듭니다(약 7시간)."

Write-Output "=== $(Get-Date -Format s) [2/3] FAQ answers ==="
& .\.venv\Scripts\python.exe -m scripts.generate_faq_answers --all
Write-Output "=== $(Get-Date -Format s) [3/3] product list ==="
& .\.venv\Scripts\python.exe -m scripts.export_product_list
Write-Output "=== $(Get-Date -Format s) all done ==="
Show-Toast "ReviewShift: 모두 완료" "표본 50건 분석과 FAQ 답변 갱신이 끝났어요. http://127.0.0.1:5173 에서 확인해 보세요."
[Win32.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
