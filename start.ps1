param(
    [ValidateSet('int', 'syst', 'accept')]
    [string]$Environment = 'int'
)

& "$PSScriptRoot\select-env.ps1" -Environment $Environment

Write-Host "Application is configured for $Environment"
Write-Host "Use these values from .env:"
Get-Content -Path (Join-Path $PSScriptRoot ".env")
