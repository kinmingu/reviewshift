# 자동 실행(run_expansion_pipeline.ps1) 진행을 지켜보다가 중요한 순간에 Windows 알림을 띄웁니다.
#   - 35개 상품 모두 20건 분석 완료  - 분류 완료·FAQ 생성 시작  - 전체 완료  - 도중에 멈춤(경고)
# 사용: powershell -ExecutionPolicy Bypass -File scripts\notify_pipeline.ps1 [-Test]
param([switch]$Test)

$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "data\evaluation\expansion_pipeline.log"

# === [알림] Windows 기본 토스트(추가 설치 없음) ===
function Show-Toast([string]$title, [string]$body) {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $safeTitle = [Security.SecurityElement]::Escape($title)
    $safeBody = [Security.SecurityElement]::Escape($body)
    $xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>$safeTitle</text><text>$safeBody</text></binding></visual><actions><action content='확인' arguments='ok'/></actions></toast>")
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show(
        [Windows.UI.Notifications.ToastNotification]::new($xml))
}

if ($Test) {
    Show-Toast "ReviewShift 알림 시험" "이 알림이 보이면 자동 실행 완료 알림도 받을 수 있어요."
    exit 0
}

# === [감시] 1분마다 로그를 읽어 새로 도달한 단계만 한 번씩 알립니다 ===
$sent = @{}
$milestones = @(
    @{ key = "stage20"; pattern = "단계 30건 시작"; title = "ReviewShift: 35개 상품 20건씩 분석 완료";
       body = "모든 상품에 결과가 생겼어요. http://127.0.0.1:5173 에서 확인하세요. 나머지 분석은 계속 진행 중입니다." },
    @{ key = "classified"; pattern = "\[3/3\] FAQ answers"; title = "ReviewShift: AI 표본 분류 완료";
       body = "35개 상품 표본 분류가 끝났어요. 이어서 FAQ 답변을 만드는 중입니다(약 4~5시간)." },
    @{ key = "done"; pattern = "all done"; title = "ReviewShift: 자동 실행 모두 완료";
       body = "분류와 FAQ 답변 생성이 모두 끝났어요. 화면과 챗봇을 확인해 보세요." }
)
while ($true) {
    $text = if (Test-Path $log) { Get-Content $log -Raw -Encoding utf8 } else { "" }
    foreach ($m in $milestones) {
        if (-not $sent[$m.key] -and $text -match $m.pattern) {
            Show-Toast $m.title $m.body
            $sent[$m.key] = $true
        }
    }
    if ($sent["done"]) { break }
    $running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "run_expansion_pipeline" -and $_.ProcessId -ne $PID -and $_.CommandLine -notmatch "notify_pipeline" }
    if (-not $running) {
        Show-Toast "ReviewShift: 자동 실행이 멈췄어요" "완료 전에 멈췄어요. scripts\run_expansion_pipeline.ps1 을 다시 실행하면 이어서 처리합니다."
        break
    }
    Start-Sleep -Seconds 60
}
