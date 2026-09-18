$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$output = Join-Path $root 'artifacts\draft_ml\v83-distributional'
$log = Join-Path $output 'launcher.log'
$errorLog = Join-Path $output 'launcher-error.log'
New-Item -ItemType Directory -Force -Path $output | Out-Null
Set-Location $root
try {
    & $python scripts\draft_v83_distributional.py --execute *>&1 | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) { throw "V8.3 exited with code $LASTEXITCODE" }
    Write-Host "V8.3 stopped at its final state. See $output\status.json" -ForegroundColor Green
} catch {
    $_ | Out-String | Set-Content -Path $errorLog
    Write-Host "FAILED. Progress retained. See $errorLog" -ForegroundColor Red
}
Write-Host 'Finished or stopped at a gate. Press Enter to close:'
[void](Read-Host)
