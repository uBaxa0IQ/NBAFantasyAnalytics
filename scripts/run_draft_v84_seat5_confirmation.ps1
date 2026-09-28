$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$output = Join-Path $root 'artifacts\draft_ml\v84-seat5-confirmation'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$log = Join-Path $output 'launcher.log'

Write-Host 'V8.4 seat-5 H2H confirmation: resumes completed scenarios.'
Write-Host "Progress: $output\progress.json"
Write-Host "Log: $log"

& python scripts\draft_v84_seat5_confirmation.py --execute *>&1 | Tee-Object -FilePath $log
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host "FAILED (exit $code). Completed scenarios remain saved." -ForegroundColor Red
} else {
    Write-Host "COMPLETE. Results: $output\summary.json" -ForegroundColor Green
}
Read-Host 'Press Enter to close'
exit $code
