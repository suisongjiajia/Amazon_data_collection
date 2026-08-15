$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".python\python.exe"

if (-not (Test-Path $python)) {
  throw "Python executable not found at $python"
}

Push-Location (Join-Path $root "backend")
try {
  & $python -m uvicorn main:app --reload --host 127.0.0.1 --port 3001
}
finally {
  Pop-Location
}
