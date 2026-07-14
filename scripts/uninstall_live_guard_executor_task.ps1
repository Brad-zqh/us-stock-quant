$ErrorActionPreference = "Stop"

$taskName = "皓量化-实盘控仓执行器"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "已卸载计划任务: $taskName"
} else {
    Write-Host "未找到计划任务: $taskName"
}
