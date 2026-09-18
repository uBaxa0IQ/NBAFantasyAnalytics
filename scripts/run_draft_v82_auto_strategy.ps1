param([switch]$Execute)
$ErrorActionPreference='Stop'; Set-Location (Split-Path -Parent $PSScriptRoot)
if(-not $Execute){python scripts/draft_v82_auto_strategy.py;exit $LASTEXITCODE}
$runOutput='E:\NBAFantasyAnalytics\artifacts\draft_ml\v82-auto-strategy';New-Item -ItemType Directory -Force -Path $runOutput|Out-Null
foreach($threadKey in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')){[Environment]::SetEnvironmentVariable($threadKey,'1','Process')}
$existing=Get-CimInstance Win32_Process|Where-Object{($_.Name -in @('python.exe','pythonw.exe'))-and($_.CommandLine -like '*draft_v82_auto_strategy.py*--execute*')}
if($existing){throw "V8.2 worker already running: $($existing.ProcessId -join ', ')"}
$pythonExe=(Get-Command python).Source;$stamp=Get-Date -Format 'yyyyMMdd-HHmmss';$errorLog="$runOutput\error-$stamp.log"
$worker=Start-Process -FilePath $pythonExe -ArgumentList @('-u','scripts/draft_v82_auto_strategy.py','--execute') -WorkingDirectory 'E:\NBAFantasyAnalytics' -WindowStyle Hidden -RedirectStandardOutput "$runOutput\out-$stamp.log" -RedirectStandardError $errorLog -PassThru
$workerHandle=$worker.Handle;$worker.Id|Set-Content -LiteralPath "$runOutput\worker.pid"
Write-Host "V8.2 AUTO-STRATEGY. Worker PID: $($worker.Id). Viewer may be closed safely."
Write-Host 'Rollout labels -> GPU strategy scorer -> validation gate -> sealed holdout. No promotion.'
while(-not $worker.HasExited){
 if(Test-Path "$runOutput\status.json"){
  try{$status=Get-Content "$runOutput\status.json" -Raw|ConvertFrom-Json;Write-Host "$(Get-Date -Format HH:mm:ss) | $($status.phase) | stages: $($status.completed)/$($status.total)"
   if(Test-Path "$runOutput\stage-progress.json"){$progress=Get-Content "$runOutput\stage-progress.json" -Raw|ConvertFrom-Json;$eta=if($null-ne$progress.eta_seconds){'{0:N1} h'-f($progress.eta_seconds/3600)}else{'measuring'};Write-Host "$($progress.stage): $($progress.completed)/$($progress.total) | remaining: $eta"}
  }catch{Write-Host 'Status update in progress...' -ForegroundColor DarkGray}
 }
 Start-Sleep -Seconds 15;$worker.Refresh()
}
$worker.WaitForExit();$status=if(Test-Path "$runOutput\status.json"){Get-Content "$runOutput\status.json" -Raw|ConvertFrom-Json}else{$null}
if($status.phase-eq'COMPLETE'){Write-Host 'COMPLETE. V8.2 holdout saved; stopped for review.' -ForegroundColor Green}elseif($status.phase-eq'STOP_FOR_REVIEW'){Write-Host 'STOPPED AT VALIDATION GATE. V8.1.1 remains champion.' -ForegroundColor Yellow}else{Write-Host "FAILED OR UNCONFIRMED. Progress retained. Read status.json and $errorLog" -ForegroundColor Red}
Read-Host 'Press Enter to close'
