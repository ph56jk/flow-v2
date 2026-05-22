param()

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.11 -m unittest discover -s tests -v
    exit $LASTEXITCODE
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} else {
    throw "Khong tim thay Python. Hay chay .\scripts\run_flow_web.ps1 -PrepareOnly truoc."
}

& $python -m unittest discover -s tests -v
