$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$artifactRoot = Join-Path $repoRoot "artifacts\draft_ml\standard8"
$dataset = Join-Path $artifactRoot "standard8-v2.jsonl.gz"
$resumeSeed = Join-Path $artifactRoot "standard8-v2-recovery-source.jsonl.gz"
$checkpoint = Join-Path $artifactRoot "checkpoints\standard8-v2"
$teacherCheckpoint = Join-Path $artifactRoot "checkpoints\standard8-v1"
$testReport = Join-Path $artifactRoot "standard8-v2-test.json"
$benchmarkReport = Join-Path $artifactRoot "standard8-v2-selfplay-market.json"
$logFile = Join-Path $artifactRoot "standard8-v2-overnight.log"
$runOutputRoot = Join-Path $artifactRoot "v2-stage-output"

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
New-Item -ItemType Directory -Force -Path $runOutputRoot | Out-Null
Start-Transcript -Path $logFile -Append | Out-Null

function Write-Stage([string]$message) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor DarkGray
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $message" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkGray
}

function Invoke-TrackedPython {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$ProgressPath = ""
    )
    $safeName = $Name.ToLower().Replace(" ", "-")
    $stdout = Join-Path $runOutputRoot "$safeName.stdout.log"
    $stderr = Join-Path $runOutputRoot "$safeName.stderr.log"
    $started = Get-Date
    $process = Start-Process python `
        -ArgumentList $Arguments `
        -WorkingDirectory $repoRoot `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr

    while (-not $process.WaitForExit(60000)) {
        $elapsed = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
        $progress = ""
        if ($ProgressPath -and (Test-Path $ProgressPath)) {
            $sizeMb = [math]::Round((Get-Item $ProgressPath).Length / 1MB, 2)
            $progress = " | partial gzip: $sizeMb MB"
        }
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Name running | elapsed: $elapsed min$progress" -ForegroundColor DarkGray
    }
    $process.WaitForExit()
    if (Test-Path $stdout) { Get-Content $stdout }
    if (Test-Path $stderr) { Get-Content $stderr | Write-Host -ForegroundColor Yellow }
    if ($process.ExitCode -ne 0) {
        throw "$Name failed with exit code $($process.ExitCode)"
    }
}

try {
    if (-not (Test-Path $teacherCheckpoint)) {
        throw "Teacher checkpoint not found: $teacherCheckpoint"
    }

    Write-Stage "1/5 GENERATE LARGE 8-CAT SELF-PLAY DATASET"
    Write-Host "Resume: 47 completed episodes preserved; episodes 47-239 remain"
    Write-Host "240 total episodes | 8 candidates | 3 rollouts | 8 workers"
    Write-Host "Teacher policy: standard8-v1"
    Invoke-TrackedPython `
        -Name "Generate" `
        -ProgressPath ($dataset + ".partial.gz") `
        -Arguments @(
            "-m", "web.backend.services.draft_ml", "generate",
            "--config", "configs/draft_ml_standard8.json",
            "--episodes", "240",
            "--workers", "8",
            "--candidates", "8",
            "--rollouts", "3",
            "--policy-checkpoint", $teacherCheckpoint,
            "--start-episode", "47",
            "--seed-dataset", $resumeSeed,
            "--output", $dataset,
            "--execute"
        )

    Write-Stage "2/5 TRAIN PAIRWISE V2 POLICY + VALUE MODELS"
    Invoke-TrackedPython `
        -Name "Train" `
        -Arguments @(
            "-m", "web.backend.services.draft_ml", "train",
            "--format", "standard8",
            "--dataset", $dataset,
            "--checkpoint", $checkpoint,
            "--execute"
        )

    Write-Stage "3/5 EVALUATE UNTOUCHED TEST SPLIT"
    Invoke-TrackedPython `
        -Name "Evaluate" `
        -Arguments @(
            "-m", "web.backend.services.draft_ml", "evaluate",
            "--dataset", $dataset,
            "--checkpoint", $checkpoint,
            "--split", "test",
            "--output", $testReport,
            "--execute"
        )

    Write-Stage "4/5 DIRECT A/B AGAINST MARKET-ONLY OPPONENT FIELD"
    Write-Host "100 paired scenarios | 10 runs x 10 draft slots"
    Invoke-TrackedPython `
        -Name "Benchmark" `
        -Arguments @(
            "-m", "web.backend.services.draft_ml", "benchmark",
            "--format", "standard8",
            "--checkpoint", $checkpoint,
            "--runs-per-slot", "10",
            "--opponent-field", "market",
            "--output", $benchmarkReport,
            "--execute"
        )

    Write-Stage "5/5 PROMOTION GATE"
    $metrics = Get-Content $testReport -Raw | ConvertFrom-Json
    $benchmark = Get-Content $benchmarkReport -Raw | ConvertFrom-Json
    $adaptive = $benchmark.strategies | Where-Object id -eq "adaptive"
    $legacy = $benchmark.strategies | Where-Object id -eq "legacy_balanced"
    $vsLegacy = $benchmark.comparisons_to_legacy_balanced | Where-Object strategy -eq "adaptive"
    $vsHeuristic = $benchmark.comparisons_to_adaptive_heuristic | Select-Object -First 1

    $gateChecks = [ordered]@{
        reward_mae = ($metrics.value.reward.mae -le 0.55)
        policy_top1 = ($metrics.policy.top1_accuracy -ge 0.35)
        policy_regret = ($metrics.policy.mean_regret -le 0.20)
        self_play_ci = ($vsLegacy.delta_category_wins_ci95[0] -gt 0)
        downside = ($adaptive.worst_decile_category_wins + 0.05 -ge $legacy.worst_decile_category_wins)
    }
    $approved = @($gateChecks.Values | Where-Object { -not $_ }).Count -eq 0
    $promoted = $false
    if ($approved) {
        Write-Host "All gates passed. Promoting immutable standard8-v2 champion." -ForegroundColor Green
        Invoke-TrackedPython `
            -Name "Promote" `
            -Arguments @(
                "-m", "web.backend.services.draft_ml", "promote",
                "--format", "standard8",
                "--checkpoint", $checkpoint,
                "--metrics", $testReport,
                "--self-play", $benchmarkReport,
                "--name", "standard8-v2",
                "--execute"
            )
        $promoted = $true
    }
    else {
        Write-Host "Promotion rejected; live remains on the current heuristic." -ForegroundColor Yellow
    }

    Write-Stage "OVERNIGHT RUN COMPLETED"
    Write-Host ("Model version        : {0}" -f 2)
    Write-Host ("Test top-1 accuracy  : {0:P1}" -f $metrics.policy.top1_accuracy)
    Write-Host ("Test mean regret      : {0:N3}" -f $metrics.policy.mean_regret)
    Write-Host ("Test reward MAE       : {0:N3}" -f $metrics.value.reward.mae)
    Write-Host ("ML category wins      : {0:N3}" -f $adaptive.average_category_wins)
    Write-Host ("Delta vs legacy       : {0:+0.000;-0.000;0.000}" -f $vsLegacy.delta_category_wins)
    Write-Host ("Delta vs heuristic    : {0:+0.000;-0.000;0.000}" -f $vsHeuristic.delta_category_wins)
    Write-Host ("Promoted to live      : {0}" -f $promoted)
    Write-Host ""
    Write-Host "Promotion gates:"
    $gateChecks.GetEnumerator() | ForEach-Object {
        $status = if ($_.Value) { "PASS" } else { "FAIL" }
        Write-Host ("  {0,-18} {1}" -f $_.Key, $status)
    }
    Write-Host ""
    Write-Host "Reports:"
    Write-Host $testReport
    Write-Host $benchmarkReport
    Write-Host $logFile
}
catch {
    Write-Stage "OVERNIGHT RUN FAILED"
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Full log: $logFile"
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
    Write-Host ""
    Read-Host "Finished. Press Enter to close this window"
}
