param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$PlaywrightArgs
)

$ErrorActionPreference = "Stop"
$runId = [Guid]::NewGuid().ToString("N")
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) "novelflow-live-api-e2e-$runId"
New-Item -ItemType Directory -Path $runRoot | Out-Null
$tsconfigPath = Join-Path $PSScriptRoot "tsconfig.json"
$originalTsconfigBytes = [System.IO.File]::ReadAllBytes($tsconfigPath)

$env:INTEGRATION_RUN_ROOT = $runRoot
if (-not $env:INTEGRATION_API_PORT) { $env:INTEGRATION_API_PORT = "8187" }
if (-not $env:INTEGRATION_WEB_PORT) { $env:INTEGRATION_WEB_PORT = "3187" }

Write-Host "Isolated live API/browser run root: $runRoot"
Write-Host "API: 127.0.0.1:$($env:INTEGRATION_API_PORT); Web: 127.0.0.1:$($env:INTEGRATION_WEB_PORT)"

Push-Location $PSScriptRoot
$exitCode = 1
try {
  & npm exec -- playwright test --config=playwright.integration.config.ts --reporter=list @PlaywrightArgs
  $exitCode = $LASTEXITCODE
}
finally {
  Pop-Location
  # Next.js adds the active distDir type folder to tsconfig.json. Keep that
  # per-run generated entry out of the shared worktree and PR diff.
  [System.IO.File]::WriteAllBytes($tsconfigPath, $originalTsconfigBytes)
}

exit $exitCode
