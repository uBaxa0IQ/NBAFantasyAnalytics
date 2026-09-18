param([switch]$Execute)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not $Execute) { python scripts/draft_v75_unknown_search.py; exit $LASTEXITCODE }
$lateOutput = 'E:\NBAFantasyAnalytics\artifacts\draft_ml\standard8-v75-unknown-search'
New-Item -ItemType Directory -Force -Path $lateOutput | Out-Null
foreach ($lateKey in @('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')) {
    [Environment]::SetEnvironmentVariable($lateKey,'1','Process')
}
$latePython = (Get-Command python).Source
$lateStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$lateErrorLog = "$lateOutput\error-$lateStamp.log"
$lateEntry = @('-u','scripts/draft_v75_unknown_search.py','--execute')
$lateProcess = Start-Process -FilePath $latePython -ArgumentList $lateEntry -WorkingDirectory 'E:\NBAFantasyAnalytics' -WindowStyle Hidden -RedirectStandardOutput "$lateOutput\out-$lateStamp.log" -RedirectStandardError $lateErrorLog -PassThru
# Retain the process handle; still treat final status/report as authoritative evidence.
$lateHandle = $lateProcess.Handle
$lateProcess.Id | Set-Content -LiteralPath "$lateOutput\worker.pid"
Write-Host "UNKNOWN-OPPONENT SEARCH TEST ONLY. Worker PID: $($lateProcess.Id). No training."
Write-Host 'The viewer can be closed without stopping the worker. Do not start duplicates.'
while (-not $lateProcess.HasExited) {
    if (Test-Path "$lateOutput\status.json") {
        $lateStatus = Get-Content "$lateOutput\status.json" -Raw | ConvertFrom-Json
        if ($lateStatus.pid -eq $lateProcess.Id) {
            $lateEta = if ($null -ne $lateStatus.eta_seconds) { '{0:N1} h' -f ($lateStatus.eta_seconds/3600) } else { 'measuring first batch' }
            Write-Host "$(Get-Date -Format HH:mm:ss) | $($lateStatus.phase) | $($lateStatus.completed)/$($lateStatus.total) | remaining: $lateEta"
        }
    }
    Start-Sleep -Seconds 15
    $lateProcess.Refresh()
}
$lateProcess.WaitForExit()
$lateStatus = if (Test-Path "$lateOutput\status.json") { Get-Content "$lateOutput\status.json" -Raw | ConvertFrom-Json } else { $null }
$lateReport = if (Test-Path "$lateOutput\summary.json") { Get-Content "$lateOutput\summary.json" -Raw | ConvertFrom-Json } else { $null }
if ($lateStatus.pid -eq $lateProcess.Id -and $lateStatus.phase -eq 'COMPLETE_DIAGNOSTIC_ONLY' -and $lateStatus.completed -eq $lateStatus.total -and $lateReport.provenance -eq $lateStatus.provenance -and $lateReport.scenario_count -eq $lateStatus.total) {
    Write-Host 'COMPLETE. All scenarios saved. STOP for review; no training follows.' -ForegroundColor Green
} elseif (($lateStatus.pid -eq $lateProcess.Id -and $lateStatus.phase -eq 'FAILED') -or ($null -ne $lateProcess.ExitCode -and $lateProcess.ExitCode -ne 0)) {
    Write-Host "FAILED. Progress retained. See $lateErrorLog and status.json" -ForegroundColor Red
} else {
    Write-Host "UNCONFIRMED completion; inspect status.json and $lateErrorLog. No automatic restart." -ForegroundColor Yellow
}
Read-Host 'Press Enter to close'
