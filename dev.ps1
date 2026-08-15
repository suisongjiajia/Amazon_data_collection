$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Run these in two terminals:`n"
Write-Host "Terminal 1:"
Write-Host "  Set-Location `"$root`""
Write-Host "  .\start-backend.ps1`n"

Write-Host "Terminal 2:"
Write-Host "  Set-Location `"$root`""
Write-Host "  .\start-frontend.ps1"
