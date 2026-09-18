param([switch]$Execute, [switch]$WaitPilot)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $Execute) { python scripts/draft_v73_diagnostic.py; exit $LASTEXITCODE }
$v73Output = 'E:\NBAFantasyAnalytics\artifacts\draft_ml\standard8-v73-diagnostic'
New-Item -ItemType Directory -Force -Path $v73Output | Out-Null
foreach ($v73Key in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($v73Key, '1', 'Process')
}
# Worker never writes to this console. Selection may pause the viewer, not the job.
$v73Python = (Get-Command python).Source
$v73Args = @('-u','scripts/draft_v73_diagnostic.py','--execute')
if ($WaitPilot) { $v73Args += '--wait-pilot' }
$v73Process = Start-Process -FilePath $v73Python -ArgumentList $v73Args -WorkingDirectory 'E:\NBAFantasyAnalytics' -WindowStyle Hidden -RedirectStandardOutput "$v73Output\launcher-out.log" -RedirectStandardError "$v73Output\launcher-error.log" -PassThru
$v73Process.Id | Set-Content -LiteralPath "$v73Output\worker.pid"
Write-Host "DIAGNOSTIC ONLY. Worker PID: $($v73Process.Id). No training will start."
Write-Host 'Closing this viewer does not stop the worker. Do not launch a duplicate.'
while (-not $v73Process.HasExited) {
    if (Test-Path "$v73Output\status.json") {
        $v73Status = Get-Content "$v73Output\status.json" -Raw | ConvertFrom-Json
        $v73Eta = if ($null -ne $v73Status.eta_seconds) { '{0:N1} h' -f ($v73Status.eta_seconds / 3600) } else { 'measuring first batch' }
        Write-Host "$(Get-Date -Format HH:mm:ss) | $($v73Status.phase) | $($v73Status.completed)/$($v73Status.total) | remaining: $v73Eta"
    } elseif ($WaitPilot -and (Test-Path "$v73Output\pilot\status.json")) {
        $v73Pilot = Get-Content "$v73Output\pilot\status.json" -Raw | ConvertFrom-Json
        Write-Host "PILOT timing check: $($v73Pilot.completed)/$($v73Pilot.total). Main diagnostic starts automatically after success."
    }
    Start-Sleep -Seconds 15
    $v73Process.Refresh()
}
if ($v73Process.ExitCode -eq 0) { Write-Host 'COMPLETE DIAGNOSTIC. STOP: review results before any training.' -ForegroundColor Green }
else { Write-Host "FAILED. Read $v73Output\launcher-error.log" -ForegroundColor Red }
Read-Host 'Press Enter to close'
