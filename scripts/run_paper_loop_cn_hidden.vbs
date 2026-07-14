Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\OneDrive\Stock Quantitative Model"
sh.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
sh.Run """" & sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\StockQuantPy\pythonw.exe"" ""D:\OneDrive\Stock Quantitative Model\paper_loop_cn.py""", 0, False
