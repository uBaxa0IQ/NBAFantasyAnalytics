$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$output = Join-Path $root 'artifacts\draft_ml\v826-adaptive-labels'
$log = Join-Path $output 'launcher.log'
$errorLog = Join-Path $output 'launcher-error.log'
New-Item -ItemType Directory -Force -Path $output | Out-Null
Set-Location $root
try {
    & $python scripts\draft_v826_adaptive_labels.py --execute *>&1 | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) { throw "V8.2.6 exited with code $LASTEXITCODE" }
    Write-Host "COMPLETE V8.2.6. Results: $output\summary.json" -ForegroundColor Green
} catch {
    $_ | Out-String | Set-Content -Path $errorLog
    Write-Host "FAILED. Progress retained. See $errorLog" -ForegroundColor Red
}
Write-Host 'Finished or stopped at a gate. Press Enter to close:'
[void](Read-Host)
