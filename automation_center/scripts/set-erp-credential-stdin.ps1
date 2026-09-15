# Nhan mot gia tri credential ERP qua stdin va ghi vao runner\orchestrator.env
# tren host Windows, dung -Name de chon dung bien.
#
# Gia tri khong bao gio xuat hien tren command line (tranh lo qua danh sach tien
# trinh), khong in ra stdout va khong vao lich su shell.
#
# Dung tu may Mac (moi lan mot bien, chi can dien nhung bien ban co):
#   security find-generic-password -s "HaviGroup ERP MCP" -a bot-token -w \
#     | ssh hvg-pc "powershell -NoProfile -ExecutionPolicy Bypass -File C:\HaviGroup\flow-v2\automation_center\scripts\set-erp-credential-stdin.ps1 -Name ERP_BOT_TOKEN"
#
#   security find-generic-password -s "HaviGroup ERP MCP" -a api-key -w \
#     | ssh hvg-pc "powershell -NoProfile -ExecutionPolicy Bypass -File C:\HaviGroup\flow-v2\automation_center\scripts\set-erp-credential-stdin.ps1 -Name ERP_API_KEY"
#
#   security find-generic-password -s "HaviGroup ERP MCP" -a api-secret -w \
#     | ssh hvg-pc "powershell -NoProfile -ExecutionPolicy Bypass -File C:\HaviGroup\flow-v2\automation_center\scripts\set-erp-credential-stdin.ps1 -Name ERP_API_SECRET"

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('ERP_BOT_TOKEN', 'ERP_API_KEY', 'ERP_API_SECRET')]
    [string]$Name
)

$ErrorActionPreference = 'Stop'

$value = [Console]::In.ReadToEnd().Trim()
if ([string]::IsNullOrWhiteSpace($value)) {
    Write-Error 'Khong nhan duoc gia tri tu stdin.'
    exit 1
}

$envFile = 'C:\HaviGroup\flow-v2\automation_center\runner\orchestrator.env'
if (-not (Test-Path $envFile)) {
    Write-Error "Thieu $envFile"
    exit 1
}

$found = $false
$pattern = "^$Name="
$out = foreach ($line in (Get-Content -LiteralPath $envFile -Encoding UTF8)) {
    if ($line -match $pattern) {
        $found = $true
        "$Name=$value"
    } else {
        $line
    }
}
if (-not $found) { $out = @($out) + "$Name=$value" }
$out | Set-Content -LiteralPath $envFile -Encoding UTF8

# Ghi lai file lam mat ACL ke thua rieng -> siet lai.
$me = "$env:COMPUTERNAME\$env:USERNAME"
& icacls $envFile /inheritance:r | Out-Null
& icacls $envFile /grant:r "${me}:(R,W)" | Out-Null
& icacls $envFile /grant:r 'SYSTEM:(F)' | Out-Null

Write-Host "Da ghi $Name ($($value.Length) ky tu) vao $envFile"
