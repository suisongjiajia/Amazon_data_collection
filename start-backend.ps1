$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".python\python.exe"

if (-not (Test-Path $python)) {
  throw "Python executable not found at $python"
}

# 确保 Ozon 常驻 Chromium 依赖可用（已安装则很快跳过）
& $python -c "import playwright" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing playwright..."
  & $python -m pip install "playwright>=1.40.0"
  & $python -m playwright install chromium
}

Push-Location (Join-Path $root "backend")
try {
  & $python -m uvicorn main:app --reload --host 127.0.0.1 --port 3001
}
finally {
  Pop-Location
}
