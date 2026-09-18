$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$env:PYTHONUNBUFFERED = '1'
$env:DRAFT_ML_STRICT = '1'
# Generate with the heuristic, not a checkpoint trained on the old market.
$env:DRAFT_DISABLE_LEARNED = '1'
$root = Join-Path $repoRoot 'artifacts\draft_ml\standard8'
$dataset = Join-Path $root 'standard8-market-v3.jsonl.gz'
$snapshot = Join-Path $root 'standard8-market-v3-inputs.json'
$checkpoint = Join-Path $root 'checkpoints\standard8-market-v3'
$test = Join-Path $root 'standard8-market-v3-test.json'
$logs = Join-Path $root ('market-v3-run-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $logs | Out-Null
Start-Transcript -Path (Join-Path $logs 'console.log') | Out-Null
$lock = $null

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
        if ($name -eq 'generate' -and (Test-Path ($dataset + '.progress.json'))) {
            $p = Get-Content ($dataset + '.progress.json') -Raw | ConvertFrom-Json
            $progress = " | saved episodes: $($p.completed)/$($p.total)"
        }
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $name running: $minutes min$progress"
    }
    $process.WaitForExit()
    $process.Refresh()
    Get-Content $out -Tail 30
    if ((Get-Item $err).Length -gt 0) { Get-Content $err -Tail 30 }
    if ($null -eq $process.ExitCode -or $process.ExitCode -ne 0) { throw "$name failed; see $out and $err" }
}

try {
    $lock = [System.IO.File]::Open((Join-Path $root 'market-v3-run.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Write-Host '1/8 GENERATE 8-CAT: new market, 240 episodes, 8 candidates, 3 rollouts, 8 workers' -ForegroundColor Cyan
    Write-Host 'Old v2 artifacts preserved separately. Each completed episode is saved. Rerun this script to resume v3.'
    Run-Python 'generate' @('-m','web.backend.services.draft_ml','generate','--config','configs/draft_ml_standard8.json','--episodes','240','--workers','8','--candidates','8','--rollouts','3','--resume','--input-snapshot',$snapshot,'--output',$dataset,'--execute')
    Write-Host '2/8 TRAIN' -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $checkpoint 'manifest.json'))) {
        Run-Python 'train' @('-m','web.backend.services.draft_ml','train','--format','standard8','--dataset',$dataset,'--checkpoint',$checkpoint,'--execute')
    }
    Write-Host '3/8 TEST' -ForegroundColor Cyan
    Run-Python 'test' @('-m','web.backend.services.draft_ml','evaluate','--dataset',$dataset,'--checkpoint',$checkpoint,'--split','test','--output',$test,'--execute')
    $stage = 4
    foreach ($market in @('conservative','espn_draft','league_rater','category_z')) {
        Write-Host "$stage/8 PAIRED A/B: $market, 100 scenarios" -ForegroundColor Cyan
        $report = Join-Path $root "standard8-market-v3-$market.json"
        Run-Python "benchmark-$market" @('-m','web.backend.services.draft_ml','benchmark','--format','standard8','--checkpoint',$checkpoint,'--input-snapshot',$snapshot,'--runs-per-slot','10','--opponent-field','market','--market-model',$market,'--output',$report,'--execute')
        $b = Get-Content $report -Raw | ConvertFrom-Json
        $c = $b.comparisons_to_adaptive_heuristic[0]
        Write-Host ('ML vs heuristic: {0:+0.000;-0.000;0.000}, 95% CI [{1:N3}; {2:N3}]' -f $c.delta_category_wins,$c.delta_category_wins_ci95[0],$c.delta_category_wins_ci95[1])
        $stage++
    }
    Write-Host '8/8 COMPLETE. Manual review required. No automatic ML promotion/deployment.' -ForegroundColor Green
    Write-Host "Artifacts: $root"
} catch {
    Write-Host 'FAILED. Completed episode journal preserved; rerun this script after fixing the error.' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
} finally {
    if ($null -ne $lock) { $lock.Dispose() }
    Write-Host "Logs: $logs"
    try { Stop-Transcript | Out-Null } catch {}
    Read-Host 'Finished. Press Enter to close this window'
}
