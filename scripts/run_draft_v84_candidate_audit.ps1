$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = (Get-Command python).Source
$resultDir = Join-Path $projectRoot 'artifacts\draft_ml\v84-candidate-audit'
New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
Set-Location $projectRoot
try {
    & $pythonExe scripts\draft_v84_candidate_audit.py --execute *>&1 | Tee-Object -FilePath (Join-Path $resultDir 'launcher.log')
    if ($LASTEXITCODE -ne 0) { throw "V8.4 candidate audit exited with code $LASTEXITCODE" }
    Write-Host "Audit complete. Read $resultDir\summary.json" -ForegroundColor Green
} catch {
    $_ | Out-String | Set-Content -Path (Join-Path $resultDir 'launcher-error.log')
    Write-Host "Audit failed. Saved states remain in $resultDir" -ForegroundColor Red
}
Write-Host 'Press Enter to close:'
[void](Read-Host)
