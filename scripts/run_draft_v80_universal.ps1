param([switch]$Execute)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $Execute) { python scripts/draft_v80_universal.py; exit $LASTEXITCODE }
$runOutput = 'E:\NBAFantasyAnalytics\artifacts\draft_ml\standard8-v80-universal'
New-Item -ItemType Directory -Force -Path $runOutput | Out-Null
foreach ($threadKey in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($threadKey,'1','Process')
}
$pythonExe = (Get-Command python).Source
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$errorLog = "$runOutput\error-$stamp.log"
$worker = Start-Process -FilePath $pythonExe -ArgumentList @('-u','scripts/draft_v80_universal.py','--execute') `
    -WorkingDirectory 'E:\NBAFantasyAnalytics' -WindowStyle Hidden `
    -RedirectStandardOutput "$runOutput\out-$stamp.log" -RedirectStandardError $errorLog -PassThru
$workerHandle = $worker.Handle
$worker.Id | Set-Content -LiteralPath "$runOutput\worker.pid"
Write-Host "V8.0 UNIVERSAL MIGRATION. Worker PID: $($worker.Id). No training and no promotion."
Write-Host 'Exact numeric parity -> 200 full-draft parity checks -> stop for review.'
while (-not $worker.HasExited) {
    if (Test-Path "$runOutput\status.json") {
        try {
            $status = Get-Content "$runOutput\status.json" -Raw | ConvertFrom-Json
            if ($status.pid -eq $worker.Id) {
                Write-Host "$(Get-Date -Format HH:mm:ss) | $($status.phase) | stages: $($status.completed)/$($status.total)"
                if (Test-Path "$runOutput\stage-progress.json") {
                    $progress = Get-Content "$runOutput\stage-progress.json" -Raw | ConvertFrom-Json
                    if ($status.phase -eq "RUNNING:$($progress.stage)") {
                        $eta = if ($null -ne $progress.eta_seconds) { '{0:N1} min' -f ($progress.eta_seconds / 60) } else { 'measuring' }
                        Write-Host "Current: $($progress.completed)/$($progress.total) | remaining: $eta"
                    }
                }
            }
        } catch { Write-Host 'Status update in progress; retrying.' -ForegroundColor DarkGray }
    }
    Start-Sleep -Seconds 15
    $worker.Refresh()
}
$worker.WaitForExit()
$status = if (Test-Path "$runOutput\status.json") { Get-Content "$runOutput\status.json" -Raw | ConvertFrom-Json } else { $null }
if ($null -ne $status -and $status.pid -eq $worker.Id -and $status.phase -eq 'COMPLETE') {
    Write-Host 'COMPLETE. V8.0 parity passed; stopped before V8.1.' -ForegroundColor Green
} else {
    Write-Host "FAILED OR UNCONFIRMED. Read status.json and $errorLog" -ForegroundColor Red
}
Read-Host 'Press Enter to close'
