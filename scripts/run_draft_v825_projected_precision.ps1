param([switch]$Resume)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$output = Join-Path $root 'artifacts\draft_ml\v825-projected-precision'
$log = Join-Path $output 'launcher.log'
$errorLog = Join-Path $output 'launcher-error.log'
New-Item -ItemType Directory -Force -Path $output | Out-Null
Set-Location $root
try {
    & $python scripts\draft_v825_projected_precision.py --execute *>&1 | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) { throw "V8.2.5 exited with code $LASTEXITCODE" }
    Write-Host "COMPLETE V8.2.5. Results: $output\summary.json" -ForegroundColor Green
} catch {
    $_ | Out-String | Set-Content -Path $errorLog
    Write-Host "FAILED. Progress retained. See $errorLog" -ForegroundColor Red
}
Write-Host 'Finished or stopped at a gate. Press Enter to close:'
[void](Read-Host)
