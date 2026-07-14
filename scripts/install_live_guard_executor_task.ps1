$ErrorActionPreference = "Stop"

$taskName = "皓量化-实盘控仓执行器"
$root = "D:\OneDrive\Stock Quantitative Model"
$script = Join-Path $root "scripts\run_live_guard_executor.ps1"

if (-not (Test-Path $script)) {
    throw "找不到执行器脚本: $script"
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
    -Description "皓量化实盘半自动控仓执行器。只执行用户已确认的 live_guard 订单。" `
    -Force | Out-Null

Write-Host "已安装计划任务: $taskName"
Write-Host "可在任务计划程序中查看，也可运行 scripts\uninstall_live_guard_executor_task.ps1 卸载。"
