$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Push-Location (Join-Path $root "frontend")
try {
  npm run dev
}
finally {
  Pop-Location
}
