Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\OneDrive\Stock Quantitative Model"
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\OneDrive\Stock Quantitative Model\scripts\run_live_guard_executor.ps1""", 0, False
