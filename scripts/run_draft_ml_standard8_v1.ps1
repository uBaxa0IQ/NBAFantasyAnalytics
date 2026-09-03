$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$artifactRoot = Join-Path $repoRoot "artifacts\draft_ml\standard8"
$dataset = Join-Path $artifactRoot "standard8-v1.jsonl.gz"
$checkpoint = Join-Path $artifactRoot "checkpoints\standard8-v1"
$testReport = Join-Path $artifactRoot "standard8-v1-test.json"
$benchmarkReport = Join-Path $artifactRoot "standard8-v1-selfplay.json"
$logFile = Join-Path $artifactRoot "standard8-v1-run.log"

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
Start-Transcript -Path $logFile -Append | Out-Null

function Write-Stage([string]$message) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkGray
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $message" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkGray
}

try {
    Write-Stage "1/4 GENERATE 8-CAT DATASET"
    Write-Host "48 episodes, 6 candidates, 3 rollouts, 8 workers"
    python -m web.backend.services.draft_ml generate `
        --config configs/draft_ml_standard8.json `
        --episodes 48 `
        --workers 8 `
        --candidates 6 `
        --rollouts 3 `
        --output $dataset `
        --execute
    if ($LASTEXITCODE -ne 0) { throw "Dataset generation failed ($LASTEXITCODE)" }

    Write-Stage "2/4 TRAIN VALUE + POLICY MODELS"
    python -m web.backend.services.draft_ml train `
        --format standard8 `
        --dataset $dataset `
        --checkpoint $checkpoint `
        --execute
    if ($LASTEXITCODE -ne 0) { throw "Training failed ($LASTEXITCODE)" }

    Write-Stage "3/4 EVALUATE UNTOUCHED TEST SPLIT"
    python -m web.backend.services.draft_ml evaluate `
        --dataset $dataset `
        --checkpoint $checkpoint `
        --split test `
        --output $testReport `
        --execute
    if ($LASTEXITCODE -ne 0) { throw "Evaluation failed ($LASTEXITCODE)" }

    Write-Stage "4/4 PAIRED SELF-PLAY BENCHMARK"
    Write-Host "50 paired scenarios: 5 runs x 10 draft slots"
    python -m web.backend.services.draft_ml benchmark `
        --format standard8 `
        --checkpoint $checkpoint `
        --runs-per-slot 5 `
        --output $benchmarkReport `
        --execute
    if ($LASTEXITCODE -ne 0) { throw "Benchmark failed ($LASTEXITCODE)" }

    $metrics = Get-Content $testReport -Raw | ConvertFrom-Json
    $benchmark = Get-Content $benchmarkReport -Raw | ConvertFrom-Json
    $adaptive = $benchmark.strategies | Where-Object id -eq "adaptive"
    $legacy = $benchmark.strategies | Where-Object id -eq "legacy_balanced"
    $comparison = $benchmark.comparisons_to_legacy_balanced | Where-Object strategy -eq "adaptive"

    Write-Stage "COMPLETED SUCCESSFULLY"
    Write-Host ("Test top-1 accuracy : {0:P1}" -f $metrics.policy.top1_accuracy) -ForegroundColor Green
    Write-Host ("Test mean regret     : {0:N3}" -f $metrics.policy.mean_regret)
    Write-Host ("Test reward MAE      : {0:N3}" -f $metrics.value.reward.mae)
    Write-Host ("Adaptive cat wins    : {0:N3}" -f $adaptive.average_category_wins) -ForegroundColor Green
    Write-Host ("Legacy cat wins      : {0:N3}" -f $legacy.average_category_wins)
    Write-Host ("Delta vs legacy      : {0:+0.000;-0.000;0.000}" -f $comparison.delta_category_wins) -ForegroundColor Green
    Write-Host ("95% interval         : [{0:N3}, {1:N3}]" -f $comparison.delta_category_wins_ci95[0], $comparison.delta_category_wins_ci95[1])
    Write-Host ""
    Write-Host "Reports:"
    Write-Host $testReport
    Write-Host $benchmarkReport
    Write-Host $logFile
}
catch {
    Write-Stage "FAILED"
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Full log: $logFile"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    Write-Host ""
    Read-Host "Finished. Press Enter to close this window"
}
