#!/usr/bin/env python3
"""本地虚拟盘账户速览 (paper_status.py)
=====================================

读取 state/paper_account.json / state/paper_account_cn.json, 拉取最新行情后打印
美股/A股本地虚拟盘的资金、持仓、盈亏。只读查询, 不下单。

用法:
  python paper_status.py             # 两个本地虚拟盘都看
  python paper_status.py --cn        # 只看A股本地虚拟盘
  python paper_status.py --us        # 只看美股本地虚拟盘
  python paper_status.py --loop 30   # 每30秒刷新一次
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

import engine
import paper

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATE_DIR = os.path.join(_HERE, "state")

MARKETS = {
    "us": {
        "label": "🇺🇸 美股本地虚拟盘",
        "watchlist": engine.DEFAULT_WATCHLIST,
        "benchmark": engine.BENCHMARK,
        "bench_label": "QQQ",
        "state": os.path.join(_STATE_DIR, "paper_account.json"),
        "cur": "$",
    },
    "cn": {
        "label": "🇨🇳 A股本地虚拟盘",
        "watchlist": engine.A_SHARE_WATCHLIST,
        "benchmark": engine.A_BENCHMARK,
        "bench_label": "沪深300",
        "state": os.path.join(_STATE_DIR, "paper_account_cn.json"),
        "cur": "¥",
    },
}


def _fmt(x, nd=2):
    try:
        return f"{float(x):,.{nd}f}"
    except Exception:
        return str(x)


def _analyze_for_status(m: dict) -> dict:
    return engine.analyze(
        m["watchlist"],
        period="2y",
        use_news=False,
        use_fundamentals=True,
        use_earnings=False,
        benchmark=m["benchmark"],
        bench_label=m["bench_label"],
    )


def show_market(key: str, refresh_quotes: bool = True) -> None:
    m = MARKETS[key]
    cur = m["cur"]
    print("=" * 70)
    print(f"  {m['label']}  (本地JSON · 不向券商下单)")
    print("=" * 70)
    if not os.path.exists(m["state"]):
        print(f"  账户文件不存在: {m['state']}")
        print("  可先运行: python paper_loop_cn.py --once --force  (A股)")
        return

    detail = {}
    res = {}
    if refresh_quotes:
        print("  正在拉取最新行情估值...")
        try:
            res = _analyze_for_status(m)
            detail = res.get("detail", {})
        except Exception as e:
            print(f"  拉取最新行情失败, 将按成本价估值: {e!r}")
            detail = {}
            res = {}
    else:
        print("  快速模式: 不拉最新行情, 按持仓成本价估值。")

    acc = paper.load_account(m["state"])
    summ = paper.summary(acc, detail)
    regime = (res.get("regime", {}) or {}).get("label", "")
    if regime:
        print(f"  大盘环境 {regime}")
    print(f"  总资产 {cur}{_fmt(summ['total'])}   现金 {cur}{_fmt(summ['cash'])}   "
          f"持仓市值 {cur}{_fmt(summ['invested'])}")
    print(f"  累计收益 {summ['ret_pct']:+.2f}%   累计成交 {summ['n_trades']} 笔")

    rows = summ["rows"]
    if not rows:
        print("  持仓: 空仓")
        return

    print()
    print(f"  {'代码':<11}{'名称':<10}{'数量':>10}{'成本':>11}{'现价':>11}"
          f"{'市值':>12}{'盈亏':>12}{'盈亏%':>9}")
    print("  " + "-" * 86)
    tot_pl = 0.0
    for r in rows:
        qty = float(r.get("股数", 0) or 0)
        avg = float(r.get("成本价", 0) or 0)
        px = float(r.get("现价", 0) or 0)
        mv = float(r.get("市值", 0) or 0)
        pl = float(r.get("浮动盈亏", 0) or 0)
        plr = float(r.get("盈亏%", 0) or 0)
        tot_pl += pl
        print(f"  {r['代码']:<11}{str(r.get('名称',''))[:9]:<10}{qty:>10.3f}"
              f"{avg:>11.2f}{px:>11.2f}{mv:>12.2f}{pl:>+12.2f}{plr:>+8.2f}%")
    print("  " + "-" * 86)
    print(f"  持仓合计盈亏: {cur}{_fmt(tot_pl)}")


def run_once(which: str, refresh_quotes: bool) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n本地虚拟盘账户速览  {stamp}\n")
    keys = ["us", "cn"] if which == "both" else [which]
    for k in keys:
        show_market(k, refresh_quotes=refresh_quotes)


def main() -> int:
    ap = argparse.ArgumentParser(description="本地虚拟盘账户速览 (只读)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--us", action="store_true", help="只看美股本地虚拟盘")
    g.add_argument("--cn", action="store_true", help="只看A股本地虚拟盘")
    ap.add_argument("--loop", type=int, default=0, metavar="秒",
                    help="每 N 秒自动刷新 (Ctrl+C 退出)")
    ap.add_argument("--fast", action="store_true",
                    help="快速显示本地账户, 不拉最新行情")
    args = ap.parse_args()
    which = "us" if args.us else ("cn" if args.cn else "both")

    try:
        if args.loop and args.loop > 0:
            while True:
                try:
                    os.system("cls" if os.name == "nt" else "clear")
                except Exception:
                    pass
                run_once(which, refresh_quotes=not args.fast)
                print(f"\n(每 {args.loop} 秒刷新, 按 Ctrl+C 退出)")
                time.sleep(args.loop)
        else:
            run_once(which, refresh_quotes=not args.fast)
        return 0
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
