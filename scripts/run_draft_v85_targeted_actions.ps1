$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$output = Join-Path $root 'artifacts\draft_ml\v85-targeted-actions'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$log = Join-Path $output 'launcher.log'

function Run-Stage([string]$label, [string]$script, [string[]]$arguments) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $label" -ForegroundColor Cyan
    & python $script @arguments *>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) {
        throw "$label failed (exit $LASTEXITCODE). Completed scenarios remain saved."
    }
}

try {
    Write-Host "Progress and results: $output"
    Run-Stage 'GENERATE ACTION LABELS' 'scripts\draft_v85_action_data.py' @('--execute')
    $labels = Get-Content (Join-Path $output 'summary.json') | ConvertFrom-Json
    if ($labels.decision -ne 'TRAIN_EXPERIMENTAL_RANKER') {
        Write-Host "Stopped at label-quality gate: $($labels.decision)" -ForegroundColor Yellow
        exit 0
    }

    Run-Stage 'TRAIN EXPERIMENTAL RANKER' 'scripts\draft_v85_action_train.py' @('--stage', 'train')
    Run-Stage 'VALIDATE INDEPENDENTLY' 'scripts\draft_v85_action_train.py' @('--stage', 'validation')
    $validation = Get-Content (Join-Path $output 'validation\summary.json') | ConvertFrom-Json
    if (-not $validation.passed) {
        Write-Host 'Validation gate failed; sealed holdout remains unopened.' -ForegroundColor Yellow
        exit 0
    }

    Run-Stage 'OPEN SEALED HOLDOUT' 'scripts\draft_v85_action_train.py' @('--stage', 'holdout')
    Write-Host "COMPLETE. Final results: $output\holdout\summary.json" -ForegroundColor Green
} catch {
    Write-Host "FAILED: $_" -ForegroundColor Red
    exit 1
} finally {
    Read-Host 'Press Enter to close'
}
