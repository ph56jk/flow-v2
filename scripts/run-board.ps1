# Wrapper khởi động bảng điều khiển trên máy trung tâm (Scheduled Task).
#
# Bảng: https://phongdzso1tg.phonh.io.vn — hai phần, đăng Etsy và tạo ảnh.
# Máy chủ chỉ nghe 127.0.0.1:8765. Task "HaviGroup Board Tunnel" chạy
# cloudflared, đưa tên miền về cổng ấy. Chi tiết: docs/bang-dieu-khien.md.
#
# Mật khẩu không nằm trong repo. C:\HaviGroup\board\password.txt chỉ giữ mã
# băm, tạo bằng `python -m flow_web.board --hash-password`. Không có tệp ấy
# thì bảng không lên: mở ra Internet mà không khoá là không được.

$ErrorActionPreference = 'Stop'

$RepoRoot     = 'C:\HaviGroup\flow-v2'
$Python       = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$PasswordFile = 'C:\HaviGroup\board\password.txt'
# flow-v2 ghi tệp này mỗi lần job đổi. Bảng chỉ đọc, để thấy job đổi sau ~2 giây.
$FlowState    = Join-Path $RepoRoot 'data\state.json'
$HostName     = 'phongdzso1tg.phonh.io.vn'
$Port         = 8765

if (-not (Test-Path $Python)) {
    Write-Error "Thiếu .venv: $Python"
    exit 78
}
if (-not (Test-Path $PasswordFile)) {
    Write-Error "Thiếu $PasswordFile — tạo bằng: python -m flow_web.board --hash-password"
    exit 78
}

Set-Location -LiteralPath $RepoRoot

$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# Bản Listing và flow-v2 cùng máy: gọi thẳng 127.0.0.1, không qua Tailscale.
& $Python -m flow_web.board --no-open --port $Port `
    --listing-base 'http://127.0.0.1:8001' `
    --flow-base 'http://127.0.0.1:8000' `
    --flow-state-file $FlowState `
    --password-file $PasswordFile `
    --host-name $HostName
exit $LASTEXITCODE
