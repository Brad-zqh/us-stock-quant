Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\OneDrive\Stock Quantitative Model"
sh.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
sh.Environment("PROCESS")("LOOP_MODE") = "paper"
sh.Environment("PROCESS")("FUTU_WATCHLIST") = "SNDK,MU,STX,WDC,AMD,MRVL,SMCI,ARM,CRDO,LITE,COHR,ANET"
sh.Run """" & sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\StockQuantPy\pythonw.exe"" ""D:\OneDrive\Stock Quantitative Model\futu_loop.py""", 0, False
