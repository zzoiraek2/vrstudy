param(
    [int]$Port = 8765,
    [string]$HostName = "127.0.0.1",
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not [string]::IsNullOrWhiteSpace($DataDir)) {
    $env:VRSTUDY_DATA_DIR = $DataDir
}
python -m uvicorn vrstudy_web.app:app --host $HostName --port $Port
