<#
.SYNOPSIS
    Registers a Windows Task Scheduler job for the NSE daily stock analysis agent.

.DESCRIPTION
    Creates a task that runs scripts/run_daily.py at 08:00 every day.
    The script itself checks NSE holidays before doing any work.
    Run this script once from the project root as the same user who will run the task.

.EXAMPLE
    cd "C:\Users\saura\Claude playground\Local repos\stock-_analysis"
    .\scripts\setup_scheduler.ps1
#>

[CmdletBinding()]
param(
    [string]$RunTime  = "08:00",
    [string]$TaskName = "NSE-StockAnalysis-Daily",
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# -- Resolve paths -------------------------------------------------------------
$ProjectRoot = (Get-Item $PSScriptRoot).Parent.FullName
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EntryPoint  = Join-Path $ProjectRoot "scripts\run_daily.py"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual-env Python not found at: $VenvPython"
    exit 1
}

if (-not (Test-Path $EntryPoint)) {
    Write-Error "Entry point not found: $EntryPoint"
    exit 1
}

# -- Uninstall mode ------------------------------------------------------------
if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Task '$TaskName' removed." -ForegroundColor Green
    } else {
        Write-Host "Task '$TaskName' not found - nothing to remove."
    }
    exit 0
}

# -- Build task components -----------------------------------------------------
$Action = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument "`"$EntryPoint`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday `
    -At $RunTime

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -DisallowHardTerminate:$false

$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# -- Register or update the task -----------------------------------------------
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Set-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal | Out-Null
    Write-Host "Task '$TaskName' updated." -ForegroundColor Cyan
} else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "NSE daily stock analysis - runs every day at $RunTime" | Out-Null
    Write-Host "Task '$TaskName' registered." -ForegroundColor Green
}

# -- Summary -------------------------------------------------------------------
Write-Host ""
Write-Host "  Python   : $VenvPython"
Write-Host "  Script   : $EntryPoint"
Write-Host "  Schedule : Every day at $RunTime (local time)"
Write-Host "  Working  : $ProjectRoot"
Write-Host ""
Write-Host "To verify : Get-ScheduledTask -TaskName '$TaskName' | Select-Object TaskName,State"
Write-Host "To run now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To remove : .\scripts\setup_scheduler.ps1 -Uninstall"
