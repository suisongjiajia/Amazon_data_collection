$ErrorActionPreference = "Stop"

# Start a dedicated Chrome with CDP for Ozon collect.
# Keep that window open after finishing ozon.ru human check.

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 9222
if ($env:OZON_BROWSER_CDP_PORT) {
  $port = [int]$env:OZON_BROWSER_CDP_PORT
}
$profileDir = Join-Path $root ".ozon-chrome-profile"
$debugUrl = "http://127.0.0.1:$port"
$startUrl = "https://www.ozon.ru/"
$startUrl1688 = "https://air.1688.com/app/1688-lp/landing-page/home/inventory/products.html?bizType=browser&customerId=AIBUY"
$startUrlSeller = "https://seller.ozon.ru/app/dashboard/main"

function Find-Chrome {
  $candidates = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
  )
  foreach ($path in $candidates) {
    if (Test-Path $path) { return $path }
  }
  return $null
}

function Test-Cdp {
  try {
    $resp = Invoke-WebRequest -Uri "$debugUrl/json/version" -UseBasicParsing -TimeoutSec 2
    return ($resp.StatusCode -eq 200)
  } catch {
    return $false
  }
}

function Open-CollectTabs {
  foreach ($url in @($startUrl, $startUrl1688, $startUrlSeller)) {
    try {
      Invoke-WebRequest -Uri "$debugUrl/json/new?$([uri]::EscapeDataString($url))" -Method Put -UseBasicParsing -TimeoutSec 3 | Out-Null
    } catch {
      try { Start-Process $url } catch { }
    }
  }
}

function Show-ChromeWindows {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinActivate {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
  Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object {
    [WinActivate]::ShowWindow($_.MainWindowHandle, 9) | Out-Null
    [WinActivate]::SetForegroundWindow($_.MainWindowHandle) | Out-Null
  }
}

$chrome = Find-Chrome
if (-not $chrome) {
  throw "Google Chrome not found. Install Chrome first."
}

if (Test-Cdp) {
  Write-Host "[ok] Chrome CDP already running: $debugUrl"
  Open-CollectTabs
  Show-ChromeWindows
  Write-Host "[next] Keep Chrome open: ozon.ru + 1688 image-search + seller.ozon.ru (logged in)."
  exit 0
}

New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

# Newer Chrome requires remote-allow-origins for CDP clients.
$argList = @(
  "--remote-debugging-port=$port",
  "--remote-allow-origins=*",
  "--user-data-dir=$profileDir",
  "--no-first-run",
  "--no-default-browser-check",
  "--disable-features=Translate,MediaRouter",
  "--new-window",
  $startUrl
)

Write-Host "[start] Launching dedicated Chrome..."
Write-Host "[chrome] $chrome"
Write-Host "[profile] $profileDir"
Write-Host "[cdp] $debugUrl"

$proc = Start-Process -FilePath $chrome -ArgumentList $argList -PassThru
Write-Host "[pid] $($proc.Id)"

$ready = $false
for ($i = 1; $i -le 15; $i++) {
  Start-Sleep -Milliseconds 800
  if (Test-Cdp) {
    $ready = $true
    break
  }
}

if (-not $ready) {
  Write-Host ""
  Write-Host "[fail] Chrome did not expose CDP on $debugUrl"
  Write-Host "Possible causes:"
  Write-Host "  1) Another Chrome holds this profile (close it and retry)"
  Write-Host "  2) Antivirus blocked remote debugging"
  Write-Host "  3) Window opened behind other apps - check taskbar"
  Write-Host "Tip: fully quit Chrome from tray, then rerun this script."
  exit 1
}

# Open 1688 + seller tabs after CDP is ready
foreach ($url in @($startUrl1688, $startUrlSeller)) {
  try {
    Invoke-WebRequest -Uri "$debugUrl/json/new?$([uri]::EscapeDataString($url))" -Method Put -UseBasicParsing -TimeoutSec 3 | Out-Null
  } catch { }
}

Show-ChromeWindows
Write-Host "[ok] Chrome CDP is ready: $debugUrl"
Write-Host "[next] Login these tabs and KEEP open: ozon.ru / 1688 products / seller.ozon.ru"
Write-Host "[1688] $startUrl1688"
Write-Host "[seller] $startUrlSeller"
