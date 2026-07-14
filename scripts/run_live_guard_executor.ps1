$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$env:FUTU_ALLOW_LIVE = "1"

$root = "D:\OneDrive\Stock Quantitative Model"
$py = Join-Path $env:LOCALAPPDATA "StockQuantPy\python.exe"
$log = Join-Path $root "futu_live_guard_executor.log"

Set-Location $root
& $py "futu_live_guard.py" "--executor-loop" "--poll-sec" "20" *>> $log
