# 本地桌面启动器

这些脚本是 Windows 本机辅助入口, 用 `pythonw.exe` 静默启动, 避免弹出 `python.exe` 控制台窗口。

- `open_account_dashboard.vbs`: 生成并打开账户看板。
- `run_futu_loop_hidden.vbs`: 静默启动美股富途模拟盘自动交易循环。
- `run_paper_loop_cn_hidden.vbs`: 静默启动 A 股本地虚拟盘自动交易循环。
- `run_live_guard_executor_hidden.vbs`: 静默启动美股富途实盘半自动控仓执行器，只执行你已确认的 `live_guard` 订单。
- `install_live_guard_executor_task.ps1`: 安装 Windows 登录后自动启动的实盘执行器计划任务。
- `uninstall_live_guard_executor_task.ps1`: 卸载上面的计划任务。

实盘执行器会写日志到项目根目录 `futu_live_guard_executor.log`。它要求 Futu OpenD 在线，并在脚本里显式设置 `FUTU_ALLOW_LIVE=1`；未确认的订单不会执行。

当前脚本写死本机项目路径 `D:\OneDrive\Stock Quantitative Model`。换机器时按实际路径调整。
