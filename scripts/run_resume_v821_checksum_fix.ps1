$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$runOutput = 'E:\NBAFantasyAnalytics\artifacts\draft_ml\v821-auto-strategy'
$pythonExe = (Get-Command python).Source
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$errorLog = "$runOutput\recovery-error-$stamp.log"
$outLog = "$runOutput\recovery-out-$stamp.log"

foreach ($threadKey in @('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($threadKey, '1', 'Process')
}

$existing = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @('python.exe', 'pythonw.exe')) -and
    (($_.CommandLine -like '*resume_v821_checksum_fix.py*') -or
     ($_.CommandLine -like '*draft_v821_auto_strategy.py*--execute*'))
}
if ($existing) {
    throw "V8.2.1 worker already running: $($existing.ProcessId -join ', ')"
}

$worker = Start-Process -FilePath $pythonExe `
    -ArgumentList @('-u', 'scripts/resume_v821_checksum_fix.py') `
    -WorkingDirectory 'E:\NBAFantasyAnalytics' `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errorLog `
    -PassThru
$workerHandle = $worker.Handle
$worker.Id | Set-Content -LiteralPath "$runOutput\worker.pid"

Write-Host "V8.2.1 RECOVERY. Worker PID: $($worker.Id). Training will NOT repeat."
while (-not $worker.HasExited) {
    if (Test-Path "$runOutput\status.json") {
        try {
            $status = Get-Content "$runOutput\status.json" -Raw | ConvertFrom-Json
            Write-Host "$(Get-Date -Format HH:mm:ss) | $($status.phase) | stages: $($status.completed)/$($status.total)"
            if (Test-Path "$runOutput\stage-progress.json") {
                $progress = Get-Content "$runOutput\stage-progress.json" -Raw | ConvertFrom-Json
                $eta = if ($null -ne $progress.eta_seconds) { '{0:N1} h' -f ($progress.eta_seconds / 3600) } else { 'measuring' }
                Write-Host "$($progress.stage): $($progress.completed)/$($progress.total) | remaining: $eta"
            }
        } catch {
            Write-Host 'Status update in progress...'
        }
    }
    Start-Sleep 15
    $worker.Refresh()
}

$worker.WaitForExit()
$status = if (Test-Path "$runOutput\status.json") {
    Get-Content "$runOutput\status.json" -Raw | ConvertFrom-Json
} else {
    $null
}
if ($status.phase -eq 'COMPLETE') {
    Write-Host 'COMPLETE. Holdout saved; stopped for review.' -ForegroundColor Green
} elseif ($status.phase -eq 'STOP_FOR_REVIEW') {
    Write-Host 'STOPPED AT VALIDATION. V8.1.1 remains champion.' -ForegroundColor Yellow
} else {
    Write-Host "FAILED. Progress retained. Read $errorLog and status.json" -ForegroundColor Red
}
Read-Host 'Press Enter to close'
