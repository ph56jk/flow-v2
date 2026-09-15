# Wrapper khởi động Review Lister trên máy trung tâm (Scheduled Task).
#
# Việc của nó: quét cột *Đang review* của ERP và đẩy thẻ đã khai `account` +
# `copysku` sang bản Listing để dựng bản nháp Etsy. Chi tiết và cách gỡ lỗi:
# docs/bat-listing-etsy.md, mục "Cột Đang review → Etsy".
#
# Trước 11/09/2026 tiến trình này dựng bằng tay, máy khởi động lại là mất.
# Task gọi script này nên có BootTrigger; MultipleInstancesPolicy là IgnoreNew
# để không bao giờ có hai bản cùng quét — hai bản là hai bản nháp cho một thẻ.
#
# Không nạp file .env nào: `flow_web.review_lister` tự đọc .env.local ở gốc
# repo (`build_from_env`). Script không in giá trị biến nào ra log.

$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\HaviGroup\flow-v2'
$Python   = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$EnvFile  = Join-Path $RepoRoot '.env.local'

# Giây giữa hai lượt quét. Mỗi lượt soi tối đa 5 thẻ bằng taskFull; token bot
# có trần 60 request/phút và agent bot dùng chung nó, nên đừng hạ số này.
$LoopSeconds = 300

if (-not (Test-Path $Python)) {
    Write-Error "Thiếu .venv: $Python"
    exit 78
}
if (-not (Test-Path $EnvFile)) {
    Write-Error "Thiếu $EnvFile — lister cần ERP_LISTING_API_URL và ERP_LISTING_FILES_DIR"
    exit 78
}

# Task có trigger lặp 5 phút để tự dựng lại lister bị giết. IgnoreNew chỉ chặn
# bản thứ hai của chính task: lister chạy tay bằng `--loop` thì task không biết.
# Thấy một vòng quét khác đang chạy thì thôi, kẻo hai bản nháp cho một thẻ.
$other = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'flow_web\.review_lister' -and $_.CommandLine -match '--loop' })
if ($other.Count -gt 0) {
    Write-Output ("Đã có lister đang quét (pid {0}), không bật thêm." -f (($other | ForEach-Object { $_.ProcessId }) -join ', '))
    exit 0
}

Set-Location -LiteralPath $RepoRoot

$env:PYTHONUNBUFFERED = '1'
# Console Windows mac dinh la cp1252; lister in thong bao tieng Viet nen se
# crash voi UnicodeEncodeError neu khong bat che do UTF-8.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

& $Python -m flow_web.review_lister --loop $LoopSeconds
exit $LASTEXITCODE
