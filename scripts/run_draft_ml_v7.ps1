param([switch]$Execute, [switch]$Preflight)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $Execute) {
    if ($Preflight) { python scripts/draft_ml_v7_run.py --preflight }
    else { python scripts/draft_ml_v7_run.py }
    exit $LASTEXITCODE
}
try {
    python -u scripts/draft_ml_v7_run.py --execute
    if ($LASTEXITCODE -ne 0) { throw 'V7 failed. Check logs; saved progress is preserved.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
} finally {
    Read-Host 'Finished or stopped at a gate. Press Enter to close'
}
