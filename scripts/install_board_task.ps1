# Đăng ký hai Scheduled Task cho bảng điều khiển trên máy trung tâm.
#
# Chạy trên hvg-pc, trong cửa sổ PowerShell **có quyền admin**:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\HaviGroup\flow-v2\scripts\install_board_task.ps1
#
# - "HaviGroup Board": python -m flow_web.board, nghe 127.0.0.1:8765.
# - "HaviGroup Board Tunnel": cloudflared, đưa https://phongdzso1tg.phonh.io.vn
#   về cổng ấy. Cần tệp khoá của tunnel (<id>.json) trong $TunnelDir; tạo tunnel
#   và bản ghi DNS: docs/bang-dieu-khien.md, mục "Dựng lại từ đầu".
#
# Cả hai có BootTrigger + LogonTrigger: máy khởi động lại là bảng tự lên. Thêm
# một trigger lặp 5 phút: tiến trình bị giết thì trong 5 phút tự bật lại.

param(
    [string]$RepoRoot    = "C:\HaviGroup\flow-v2",
    [string]$TunnelDir   = "C:\HaviGroup\cloudflared",
    [string]$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    [string]$HostName    = "phongdzso1tg.phonh.io.vn",
    [int]$Port           = 8765,
    [string]$LogDir      = "C:\HaviGroup\logs"
)

$ErrorActionPreference = "Stop"

$wrapper = Join-Path $RepoRoot "scripts\run-board.ps1"
if (-not (Test-Path $wrapper)) { throw "Thiếu wrapper: $wrapper" }
if (-not (Test-Path $Cloudflared)) { throw "Thiếu cloudflared: $Cloudflared" }
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# config.yml của tunnel: dựng từ tệp khoá nếu chưa có. Tệp khoá mang TunnelID.
$config = Join-Path $TunnelDir "config.yml"
if (-not (Test-Path $config)) {
    $keys = @(Get-ChildItem $TunnelDir -Filter "*.json" -ErrorAction SilentlyContinue)
    if ($keys.Count -ne 1) { throw "Cần đúng một tệp khoá tunnel (*.json) trong $TunnelDir, đang có $($keys.Count)" }
    $id = (Get-Content $keys[0].FullName -Raw | ConvertFrom-Json).TunnelID
    if (-not $id) { throw "Tệp $($keys[0].Name) không có TunnelID" }
    $lines = @(
        "tunnel: $id",
        "credentials-file: $($keys[0].FullName)",
        "logfile: $(Join-Path $LogDir 'cloudflared.log')",
        "no-autoupdate: true",
        "ingress:",
        "  - hostname: $HostName",
        "    service: http://127.0.0.1:$Port",
        "  - service: http_status:404"
    )
    [IO.File]::WriteAllLines($config, $lines)
    Write-Host "Đã ghi $config (tunnel $id)"
}

# Máy này không vào domain nên $env:USERDOMAIN là "WORKGROUP". Tài khoản thật
# là <tên máy>\<người dùng>, ví dụ PC\Admin.
$account = "{0}\{1}" -f $env:COMPUTERNAME, $env:USERNAME
# RestartCount chỉ chạy lại khi task không khởi động được. Tiến trình bị giết
# (script deploy flow-v2 giết mọi python khớp 'flow_web') thì task nằm im. Trigger
# lặp dựng lại nó; đang chạy thì IgnoreNew bỏ qua lượt ấy.
$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn -User $account),
    (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5))
)
# ExecutionTimeLimit 0 = không cắt: cả hai là tiến trình chạy mãi.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType S4U -RunLevel Highest

$tasks = @(
    @{
        Name = "HaviGroup Board"
        Match = 'flow_web\.board'
        Action = New-ScheduledTaskAction -Execute "cmd.exe" -WorkingDirectory $RepoRoot `
            -Argument ('/c powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" >> "{1}" 2>&1' -f $wrapper, (Join-Path $LogDir "board.log"))
        Description = "Bảng điều khiển HaviGroup (flow_web.board) trên 127.0.0.1:$Port."
    },
    @{
        Name = "HaviGroup Board Tunnel"
        # Chỉ khớp tunnel của bảng: máy có thể chạy tunnel khác, đừng giết nhầm.
        Match = [regex]::Escape($config)
        Action = New-ScheduledTaskAction -Execute $Cloudflared -WorkingDirectory $TunnelDir `
            -Argument ('tunnel --config "{0}" run' -f $config)
        Description = "Cloudflare Tunnel: https://$HostName -> 127.0.0.1:$Port."
    }
)

foreach ($t in $tasks) {
    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $t.Match } | ForEach-Object {
        Write-Host ("Dừng bản đang chạy: pid {0}" -f $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Register-ScheduledTask -TaskName $t.Name -Action $t.Action -Trigger $triggers -Settings $settings `
        -Principal $principal -Description $t.Description -Force | Out-Null
    Start-ScheduledTask -TaskName $t.Name
}
Start-Sleep -Seconds 3
Get-ScheduledTask -TaskName "HaviGroup Board*" | Select-Object TaskName, State
