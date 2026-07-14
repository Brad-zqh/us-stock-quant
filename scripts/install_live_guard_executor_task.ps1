$ErrorActionPreference = "Stop"

$taskName = "BradQuant-LiveGuard-Executor"
$root = "D:\OneDrive\Stock Quantitative Model"
$script = Join-Path $root "scripts\run_live_guard_executor.ps1"

if (-not (Test-Path $script)) {
    throw "Executor script not found: $script"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 7) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Brad Quant live semi-auto guard executor. Executes approved live_guard orders only." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $taskName"
Write-Host "Uninstall with scripts\uninstall_live_guard_executor_task.ps1"
