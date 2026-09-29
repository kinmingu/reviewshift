# 추가 FAQ 6개(품질·마감, 크기·사이즈, 성능, 주요 불만, 최근 변화, 추천 대상)를 56개 상품에 빠른 요약본 RAG로 생성
# 336개 × 약 35~45초 = 약 3.5~4시간. 이미 만든 최신 답은 건너뛰므로 중단 후 다시 실행하면 이어서 처리합니다.
# 실행 중에는 절전을 막고, 끝나면 Windows 알림을 띄웁니다.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8  # 로그의 한글이 깨지지 않게
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# === [절전 방지] 이 스크립트가 도는 동안만 시스템 절전을 막습니다 ===
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[Win32.Power]::SetThreadExecutionState([uint32]"0x80000001") | Out-Null

Write-Output "=== $(Get-Date -Format s) extra FAQ (fast RAG) ==="
& .\.venv\Scripts\python.exe -m scripts.generate_faq_answers --all --fast `
    --only quality --only size --only performance --only top_complaint --only recent_change --only fit_for
Write-Output "=== $(Get-Date -Format s) all done ==="

# === [완료 알림] ===
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>ReviewShift: 추가 FAQ 생성 완료</text><text>상품마다 자주 묻는 질문이 12개가 됐어요. 로그: data\evaluation\faq_extra.log</text></binding></visual><actions><action content='확인' arguments='ok'/></actions></toast>")
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
} catch {
    Write-Output "toast failed: $_"
}
[Win32.Power]::SetThreadExecutionState([uint32]"0x80000000") | Out-Null
