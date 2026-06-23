#!/usr/bin/env python3
"""
每日盘前推送入口 (run_daily.py)
==============================
被 launchd / cron 定时调用, 跑一次分析并按 config.json 推送邮件+微信。

手动测试:  python3 run_daily.py
"""
import sys
import datetime as dt

import notify


def main():
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] 开始每日推送…")
    out = notify.run_and_push(email=True, wechat=True)
    print(out.get("email", "邮件: 跳过"))
    print(out.get("wechat", "微信: 跳过"))
    print(f"[{stamp}] 完成。")


if __name__ == "__main__":
    sys.exit(main())
