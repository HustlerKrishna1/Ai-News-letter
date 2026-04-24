# Register a Windows Task Scheduler job that runs the newsletter daily.
#
# Usage (PowerShell, from project root):
#   .\scripts\schedule_windows.ps1                         # daily at 07:00 local
#   .\scripts\schedule_windows.ps1 -Time 09:30              # custom time
#   .\scripts\schedule_windows.ps1 -WithEmail               # pass --email
#   .\scripts\schedule_windows.ps1 -Remove                  # unregister
#
# The task runs whether you are logged on or not (if the account allows it).

[CmdletBinding()]
param(
    [string]$Time = "07:00",
    [string]$TaskName = "NewsletterAI-Daily",
    [switch]$WithEmail,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task: $TaskName"
    exit 0
}

$projectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$python = (Get-Command python).Source
if (-not $python) {
    throw "Could not find python on PATH. Activate your venv or install Python, then retry."
}

$args = "`"$projectRoot\main.py`""
if ($WithEmail) {
    $args += " --email"
}

$action = New-ScheduledTaskAction -Execute $python -Argument $args -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Registered '$TaskName' to run daily at $Time."
Write-Host "Python:  $python"
Write-Host "Script:  $projectRoot\main.py"
if ($WithEmail) { Write-Host "Flags:   --email" }
Write-Host "Remove with:  .\scripts\schedule_windows.ps1 -Remove"
