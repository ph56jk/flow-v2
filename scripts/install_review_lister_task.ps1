# Đăng ký Scheduled Task chạy Review Lister trên máy trung tâm.
#
# Chạy trên hvg-pc, trong cửa sổ PowerShell **có quyền admin**:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\HaviGroup\flow-v2\scripts\install_review_lister_task.ps1
#
# Task có BootTrigger + LogonTrigger nên máy khởi động lại là lister tự lên;
# trước 11/09/2026 tiến trình này dựng bằng tay và mất sau mỗi lần reboot.
# Thêm một trigger lặp 5 phút: lister bị giết thì trong 5 phút tự bật lại.
#
# Hai bản lister cùng quét là hai bản nháp Etsy cho một thẻ. Nên script dừng
# mọi tiến trình lister đang chạy tay trước khi bật task, và task đặt
# MultipleInstances IgnoreNew.

param(
    [string]$TaskName = "HaviGroup Review Lister",
    [string]$RepoRoot = "C:\HaviGroup\flow-v2",
    [string]$LogFile  = "C:\HaviGroup\logs\review-lister.log"
)

$ErrorActionPreference = "Stop"

$wrapper = Join-Path $RepoRoot "scripts\run-review-lister.ps1"
if (-not (Test-Path $wrapper)) {
    throw "Thiếu wrapper: $wrapper"
}
$logDir = Split-Path -Parent $LogFile
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Dừng bản chạy tay. Lượt quét đang giữa đường thì thẻ ấy chưa vào sổ, lượt sau
# lister hỏi hàng đợi bản Listing trước khi giao nên không thành hai bản nháp.
$running = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'flow_web\.review_lister' }
foreach ($p in $running) {
    Write-Host ("Dừng lister đang chạy: pid {0}" -f $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

$arguments = '/c powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" >> "{1}" 2>&1' -f $wrapper, $LogFile

# Máy này không vào domain nên $env:USERDOMAIN là "WORKGROUP" — Task Scheduler
# không tra ra tên ấy. Tài khoản thật là <tên máy>\<người dùng>, ví dụ PC\Admin.
$account = "{0}\{1}" -f $env:COMPUTERNAME, $env:USERNAME

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $arguments -WorkingDirectory $RepoRoot

# RestartCount chỉ chạy lại khi task không khởi động được. Tiến trình bị giết
# thì task coi như xong và nằm im: 11/09/2026 script deploy flow-v2 giết mọi
# python khớp 'flow_web' và lister im 15 phút. Trigger lặp dựng lại nó; lister
# đang chạy thì IgnoreNew bỏ qua lượt ấy.
$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn -User $account),
    (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5))
)

# ExecutionTimeLimit 0 = không cắt: lister là vòng quét không có điểm kết thúc.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries = $false

$principal = New-ScheduledTaskPrincipal `
    -UserId $account `
    -LogonType S4U `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Quét cột Đang review của ERP và dựng bản nháp Etsy (flow_web.review_lister --loop 300)." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
