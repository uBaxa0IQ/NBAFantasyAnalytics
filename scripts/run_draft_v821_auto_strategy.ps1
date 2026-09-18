param([switch]$Execute)
$ErrorActionPreference='Stop';Set-Location(Split-Path -Parent $PSScriptRoot)
if(-not $Execute){python scripts/draft_v821_auto_strategy.py;exit $LASTEXITCODE}
$runOutput='E:\NBAFantasyAnalytics\artifacts\draft_ml\v821-auto-strategy';New-Item -ItemType Directory -Force -Path $runOutput|Out-Null
foreach($threadKey in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS')){[Environment]::SetEnvironmentVariable($threadKey,'1','Process')}
$existing=Get-CimInstance Win32_Process|Where-Object{($_.Name -in @('python.exe','pythonw.exe'))-and($_.CommandLine -like '*draft_v821_auto_strategy.py*--execute*')};if($existing){throw "V8.2.1 already running: $($existing.ProcessId -join ', ')"}
$pythonExe=(Get-Command python).Source;$stamp=Get-Date -Format 'yyyyMMdd-HHmmss';$errorLog="$runOutput\error-$stamp.log"
$worker=Start-Process -FilePath $pythonExe -ArgumentList @('-u','scripts/draft_v821_auto_strategy.py','--execute') -WorkingDirectory 'E:\NBAFantasyAnalytics' -WindowStyle Hidden -RedirectStandardOutput "$runOutput\out-$stamp.log" -RedirectStandardError $errorLog -PassThru
$workerHandle=$worker.Handle;$worker.Id|Set-Content -LiteralPath "$runOutput\worker.pid"
Write-Host "V8.2.1 CATEGORY-BOUND ENSEMBLE. Worker PID: $($worker.Id). Viewer may be closed."
while(-not $worker.HasExited){if(Test-Path "$runOutput\status.json"){try{$s=Get-Content "$runOutput\status.json" -Raw|ConvertFrom-Json;Write-Host "$(Get-Date -Format HH:mm:ss) | $($s.phase) | stages: $($s.completed)/$($s.total)";if(Test-Path "$runOutput\stage-progress.json"){$p=Get-Content "$runOutput\stage-progress.json" -Raw|ConvertFrom-Json;$eta=if($null-ne$p.eta_seconds){'{0:N1} h'-f($p.eta_seconds/3600)}else{'measuring'};Write-Host "$($p.stage): $($p.completed)/$($p.total) | remaining: $eta"}}catch{Write-Host 'Status update in progress...'}};Start-Sleep 15;$worker.Refresh()}
$worker.WaitForExit();$s=if(Test-Path "$runOutput\status.json"){Get-Content "$runOutput\status.json" -Raw|ConvertFrom-Json}else{$null};if($s.phase-eq'COMPLETE'){Write-Host 'COMPLETE. Holdout saved; stopped for review.' -ForegroundColor Green}elseif($s.phase-eq'STOP_FOR_REVIEW'){Write-Host 'STOPPED AT VALIDATION. V8.1.1 remains champion.' -ForegroundColor Yellow}else{Write-Host "FAILED. Progress retained. Read status.json and $errorLog" -ForegroundColor Red};Read-Host 'Press Enter to close'
