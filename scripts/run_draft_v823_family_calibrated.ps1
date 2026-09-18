param([switch]$Execute)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $Execute) { python scripts/draft_v823_family_calibrated.py; exit $LASTEXITCODE }

$runOutput = 'E:\NBAFantasyAnalytics\artifacts\draft_ml\v823-family-calibrated'
New-Item -ItemType Directory -Force -Path $runOutput | Out-Null
foreach ($threadKey in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($threadKey,'1','Process')
}
$existing=Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -in @('python.exe','pythonw.exe')) -and ($_.CommandLine -like '*draft_v823_family_calibrated.py*--execute*')
}
if ($existing) { throw "V8.2.3 already running: $($existing.ProcessId -join ', ')" }

$pythonExe=(Get-Command python).Source;$stamp=Get-Date -Format 'yyyyMMdd-HHmmss';$errorLog="$runOutput\error-$stamp.log"
$worker=Start-Process -FilePath $pythonExe -ArgumentList @('-u','scripts/draft_v823_family_calibrated.py','--execute') `
    -WorkingDirectory 'E:\NBAFantasyAnalytics' -WindowStyle Hidden -RedirectStandardOutput "$runOutput\out-$stamp.log" `
    -RedirectStandardError $errorLog -PassThru
$workerHandle=$worker.Handle;$worker.Id | Set-Content -LiteralPath "$runOutput\worker.pid"
Write-Host "V8.2.3 FAMILY CALIBRATION. Worker PID: $($worker.Id). No training."
while (-not $worker.HasExited) {
    if (Test-Path "$runOutput\status.json") {
        try {
            $status=Get-Content "$runOutput\status.json" -Raw | ConvertFrom-Json
            Write-Host "$(Get-Date -Format HH:mm:ss) | $($status.phase) | stages: $($status.completed)/$($status.total)"
            if (Test-Path "$runOutput\stage-progress.json") {
                $progress=Get-Content "$runOutput\stage-progress.json" -Raw | ConvertFrom-Json
                $eta=if($null-ne$progress.eta_seconds){'{0:N1} h'-f($progress.eta_seconds/3600)}else{'measuring'}
                Write-Host "$($progress.stage): $($progress.completed)/$($progress.total) | remaining: $eta"
            }
        } catch { Write-Host 'Status update in progress...' }
    }
    Start-Sleep 15;$worker.Refresh()
}
$worker.WaitForExit();$status=if(Test-Path "$runOutput\status.json"){Get-Content "$runOutput\status.json" -Raw|ConvertFrom-Json}else{$null}
if($status.phase-eq'COMPLETE'){Write-Host 'COMPLETE. Fresh family holdout saved.' -ForegroundColor Green}
elseif($status.phase-eq'STOP_FOR_REVIEW'){Write-Host 'STOPPED AT CALIBRATION. V8.1.1 remains universal champion.' -ForegroundColor Yellow}
else{Write-Host "FAILED. Progress retained. Read status.json and $errorLog" -ForegroundColor Red}
Read-Host 'Press Enter to close'
