$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
# Each worker must use one BLAS/OpenMP thread, not compete with all other workers.
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$env:PYTHONUNBUFFERED = '1'
$env:DRAFT_ML_STRICT = '1'
Remove-Item Env:DRAFT_DISABLE_LEARNED -ErrorAction SilentlyContinue

$root = Join-Path $repoRoot 'artifacts\draft_ml\standard8'
$dataset = Join-Path $root 'standard8-v2.jsonl.gz'
$snapshot = Join-Path $root 'standard8-v2-inputs-frozen.json'
$seed = Join-Path $root 'standard8-v2-recovery-source.jsonl.gz'
$teacher = Join-Path $root 'checkpoints\standard8-v1'
$checkpoint = Join-Path $root 'checkpoints\standard8-v2-checked'
$test = Join-Path $root 'standard8-v2-checked-test.json'
$espnReport = Join-Path $root 'standard8-v2-checked-espn.json'
$categoryReport = Join-Path $root 'standard8-v2-checked-category-market.json'
$runId = Get-Date -Format 'yyyyMMdd-HHmmss'
$logs = Join-Path $root "checked-run-$runId"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs 'console.log'
Start-Transcript -Path $log | Out-Null
$lock = $null

function Stage([string]$text) {
    Write-Host "`n[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $text" -ForegroundColor Cyan
}

function Run-Python([string]$name, [string[]]$pythonArgs) {
    $out = Join-Path $logs "$name.stdout.log"
    $err = Join-Path $logs "$name.stderr.log"
    $quotedArgs = $pythonArgs | ForEach-Object { '"' + $_ + '"' }
    $process = Start-Process python -ArgumentList $quotedArgs -WorkingDirectory $repoRoot -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $process.Handle
    $started = Get-Date
    while (-not $process.WaitForExit(30000)) {
        $minutes = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
        $progress = ''
        $progressFile = $dataset + '.progress.json'
        if ($name -eq 'generate' -and (Test-Path $progressFile)) {
            $p = Get-Content $progressFile -Raw | ConvertFrom-Json
            $progress = " | saved episodes: $($p.completed)/$($p.total)"
        }
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $name running: $minutes min$progress" -ForegroundColor DarkGray
    }
    $process.WaitForExit()
    $process.Refresh()
    Get-Content $out -Tail 80
    if ((Get-Item $err).Length -gt 0) { Get-Content $err -Tail 30 | ForEach-Object { Write-Host $_ -ForegroundColor Yellow } }
    if ($null -eq $process.ExitCode -or $process.ExitCode -ne 0) { throw "$name failed; see $out and $err" }
}

try {
    # Keep two console launches from writing the same episode journal.
    $lock = [System.IO.File]::Open((Join-Path $root 'checked-run.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Stage '1/6 RESUME GENERATION: 240 episodes, 8 candidates, 3 rollouts, 8 workers'
    Write-Host 'Complete episodes are saved immediately. Existing legacy recovery files are preserved.'
    Run-Python 'generate' @('-m','web.backend.services.draft_ml','generate','--config','configs/draft_ml_standard8.json','--episodes','240','--workers','8','--candidates','8','--rollouts','3','--policy-checkpoint',$teacher,'--resume','--seed-dataset',$seed,'--input-snapshot',$snapshot,'--output',$dataset,'--execute')

    Stage '2/6 TRAIN PAIRWISE MODEL'
    if (-not (Test-Path (Join-Path $checkpoint 'manifest.json'))) {
        Run-Python 'train' @('-m','web.backend.services.draft_ml','train','--format','standard8','--dataset',$dataset,'--checkpoint',$checkpoint,'--execute')
    } else { Write-Host 'Complete checkpoint already exists; preserving it.' }

    Stage '3/6 TEST EVALUATION'
    Run-Python 'test' @('-m','web.backend.services.draft_ml','evaluate','--dataset',$dataset,'--checkpoint',$checkpoint,'--split','test','--output',$test,'--execute')

    Stage '4/6 CORRECTED A/B: ESPN DRAFT MARKET, 100 scenarios'
    Run-Python 'benchmark-espn' @('-m','web.backend.services.draft_ml','benchmark','--format','standard8','--checkpoint',$checkpoint,'--input-snapshot',$snapshot,'--runs-per-slot','10','--opponent-field','market','--market-model','espn_draft','--output',$espnReport,'--execute')

    Stage '5/6 MARKET SENSITIVITY: CATEGORY Z RANKING, 100 scenarios'
    Write-Host 'Synthetic category-specific ranking; this is NOT ESPN Player Rater.'
    Run-Python 'benchmark-category' @('-m','web.backend.services.draft_ml','benchmark','--format','standard8','--checkpoint',$checkpoint,'--input-snapshot',$snapshot,'--runs-per-slot','10','--opponent-field','market','--market-model','category_z','--output',$categoryReport,'--execute')

    Stage '6/6 COMPLETED - MANUAL REVIEW REQUIRED, NO AUTO PROMOTION'
    $m = Get-Content $test -Raw | ConvertFrom-Json
    Write-Host ('Test top-1: {0:P1} | regret: {1:N3} | reward MAE: {2:N3}' -f $m.policy.top1_accuracy,$m.policy.mean_regret,$m.value.reward.mae)
    foreach ($reportPath in @($espnReport,$categoryReport)) {
        $b = Get-Content $reportPath -Raw | ConvertFrom-Json
        $c = $b.comparisons_to_adaptive_heuristic[0]
        Write-Host ('{0}: ML vs true adaptive {1:+0.000;-0.000;0.000}, 95% CI [{2:N3}; {3:N3}]' -f $b.market_model,$c.delta_category_wins,$c.delta_category_wins_ci95[0],$c.delta_category_wins_ci95[1])
    }
    Write-Host 'Live/Docker unchanged. Legacy recovered data lack an original frozen snapshot; do not auto-deploy.' -ForegroundColor Yellow
    Write-Host "Reports: $test`n$espnReport`n$categoryReport`nLogs: $logs"
} catch {
    Stage 'FAILED - SAVED EPISODES PRESERVED'
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Logs: $logs"
} finally {
    if ($null -ne $lock) { $lock.Dispose() }
    try { Stop-Transcript | Out-Null } catch {}
    Read-Host 'Finished. Press Enter to close this window'
}
