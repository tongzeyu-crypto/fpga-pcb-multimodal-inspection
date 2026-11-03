param([int]$Port=8698,[switch]$NoBrowser)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING='utf-8'
$DemoUrl="http://127.0.0.1:$Port/"
$DemoStatus=$null
try { $DemoStatus=Invoke-RestMethod -Uri ($DemoUrl+'api/status') -TimeoutSec 2 } catch { }
if ($DemoStatus.offline_reference -eq $true -and $DemoStatus.demo.schema -eq 'IntegratedPlPsDemo/1') {
    if (-not $NoBrowser) { Start-Process $DemoUrl }
    Write-Output ('Offline demo is already running: '+$DemoUrl)
    exit 0
}
$DemoPython=Join-Path $env:USERPROFILE '.conda/envs/radio_gpu/python.exe'
if (-not (Test-Path -LiteralPath $DemoPython)) { $DemoPython=(Get-Command python -ErrorAction Stop).Source }
# Reuse the already installed local analysis dependencies when available.
$DemoDependencies='E:/PCB-Zynq-Build/submission-20261103/pydeps'
if (Test-Path -LiteralPath $DemoDependencies) { $env:PYTHONPATH=$DemoDependencies+[IO.Path]::PathSeparator+$env:PYTHONPATH }
$DemoArguments=@('-m','runtime.run_board','--demo','--port',"$Port")
if ($NoBrowser) { $DemoArguments+='--no-browser' }
& $DemoPython @DemoArguments
exit $LASTEXITCODE
