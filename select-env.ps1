param(
    [ValidateSet('int', 'syst', 'accept')]
    [string]$Environment = 'int'
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $root "env\$Environment.env"
$target = Join-Path $root ".env"

if (-not (Test-Path $source)) {
    throw "Environment file not found: $source"
}

Copy-Item -Path $source -Destination $target -Force
Write-Host "Selected environment: $Environment"
Write-Host "Current .env file:"
Get-Content -Path $target
