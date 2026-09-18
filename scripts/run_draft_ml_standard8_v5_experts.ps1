param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
if (-not $Execute) {
    python scripts/draft_ml_v5_experts.py
    Write-Host 'PLAN ONLY. Nothing started. Execution requires -Execute.' -ForegroundColor Yellow
    exit $LASTEXITCODE
}
try {
    python -u scripts/draft_ml_v5_experts.py --execute
    if ($LASTEXITCODE -ne 0) { throw 'Run failed. Check the stage log; completed stages are preserved.' }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
} finally {
    Read-Host 'Finished. Press Enter to close this window'
}
