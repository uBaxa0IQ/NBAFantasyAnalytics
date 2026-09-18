param([switch]$Execute)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $Execute) { python scripts/draft_v81_multiformat.py; exit $LASTEXITCODE }
$runOutput = 'E:\NBAFantasyAnalytics\artifacts\draft_ml\v81-multiformat'
New-Item -ItemType Directory -Force -Path $runOutput | Out-Null
foreach ($threadKey in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($threadKey,'1','Process')
}
$pythonExe = (Get-Command python).Source
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$errorLog = "$runOutput\error-$stamp.log"
$worker = Start-Process -FilePath $pythonExe -ArgumentList @('-u','scripts/draft_v81_multiformat.py','--execute') `
    -WorkingDirectory 'E:\NBAFantasyAnalytics' -WindowStyle Hidden `
    -RedirectStandardOutput "$runOutput\out-$stamp.log" -RedirectStandardError $errorLog -PassThru
$workerHandle = $worker.Handle
$worker.Id | Set-Content -LiteralPath "$runOutput\worker.pid"
Write-Host "V8.1 MULTI-FORMAT. Worker PID: $($worker.Id). Viewer may be closed without stopping it."
Write-Host 'Generate -> GPU train -> validation gate -> frozen holdout. No production promotion.'
while (-not $worker.HasExited) {
    if (Test-Path "$runOutput\status.json") {
        try {
            $status = Get-Content "$runOutput\status.json" -Raw | ConvertFrom-Json
            if ($status.pid -eq $worker.Id) {
                Write-Host "$(Get-Date -Format HH:mm:ss) | $($status.phase) | stages: $($status.completed)/$($status.total)"
                if (Test-Path "$runOutput\stage-progress.json") {
                    $progress = Get-Content "$runOutput\stage-progress.json" -Raw | ConvertFrom-Json
                    if ($status.phase -eq "RUNNING:$($progress.stage)") {
                        $eta = if ($null -ne $progress.eta_seconds) { '{0:N1} h' -f ($progress.eta_seconds / 3600) } else { 'measuring' }
                        Write-Host "Current stage: $($progress.completed)/$($progress.total) | remaining: $eta"
                    }
                }
            }
        } catch { Write-Host 'Status is being atomically updated; retrying.' -ForegroundColor DarkGray }
    }
    Start-Sleep -Seconds 15
    $worker.Refresh()
}
$worker.WaitForExit()
$status = if (Test-Path "$runOutput\status.json") { Get-Content "$runOutput\status.json" -Raw | ConvertFrom-Json } else { $null }
if ($null -ne $status -and $status.pid -eq $worker.Id -and $status.phase -eq 'COMPLETE') {
    Write-Host 'COMPLETE. V8.1 results saved; stopped for review.' -ForegroundColor Green
} elseif ($null -ne $status -and $status.pid -eq $worker.Id -and $status.phase -eq 'STOP_FOR_REVIEW') {
    Write-Host 'STOPPED AT A GATE. Later stages were not opened.' -ForegroundColor Yellow
} else {
    Write-Host "FAILED OR UNCONFIRMED. Progress retained. Read status.json and $errorLog" -ForegroundColor Red
}
Read-Host 'Press Enter to close'
