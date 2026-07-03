"""富途账户速览 (futu_status.py)
================================
连本机 FutuOpenD 网关, 打印【模拟盘 SIMULATE】和【实盘 REAL】的资金、持仓、盈亏。
只读查询, 不下任何单, 不需要交易解锁密码。

用法:
  python futu_status.py            # 两个账户都看
  python futu_status.py --paper    # 只看模拟盘
  python futu_status.py --real     # 只看实盘
  python futu_status.py --loop 60  # 每 60 秒刷新一次 (Ctrl+C 退出)

前提: 本机已启动 FutuOpenD 并登录 (默认 127.0.0.1:11111)。
"""
from __future__ import annotations
import argparse
import datetime as dt
import logging
import os
import sys

# 压掉 futu SDK 的连接/断开等 INFO 日志, 保持输出干净
logging.disable(logging.WARNING)

HOST = os.getenv("FUTU_HOST", "127.0.0.1")
PORT = int(os.getenv("FUTU_PORT", "11111"))


def _fmt(x, nd=2):
    try:
        return f"{float(x):,.{nd}f}"
    except Exception:
        return str(x)


def _from_code(code: str) -> str:
    c = str(code or "")
    return c.split(".", 1)[1] if "." in c else c


def show_account(ctx, env, env_label: str) -> None:
    from futu import RET_OK
    print("=" * 60)
    print(f"  {env_label}")
    print("=" * 60)

    # 资金
    ret, acc = ctx.accinfo_query(trd_env=env, currency="USD")
    if ret != RET_OK:
        print(f"  查询资金失败: {acc}")
        return
    a = acc.iloc[0]
    total = float(a.get("total_assets", 0) or 0)
    cash = float(a.get("us_cash", a.get("cash", 0)) or 0)
    mv = float(a.get("market_val", 0) or 0)
    upl = a.get("unrealized_pl", None)
    print(f"  总资产 ${_fmt(total)}   现金 ${_fmt(cash)}   持仓市值 ${_fmt(mv)}")
    if upl is not None and str(upl) not in ("nan", "N/A"):
        try:
            print(f"  浮动盈亏 ${_fmt(float(upl))}")
        except Exception:
            pass

    # 持仓
    ret, pos = ctx.position_list_query(trd_env=env)
    if ret != RET_OK:
        print(f"  查询持仓失败: {pos}")
        return
    rows = [r for _, r in pos.iterrows() if float(r.get("qty", 0) or 0) != 0]
    if not rows:
        print("  持仓: 空仓")
        return
    print()
    print(f"  {'代码':<7}{'名称':<10}{'数量':>9}{'成本':>11}{'现价':>11}{'市值':>11}{'盈亏$':>10}{'盈亏%':>9}")
    print("  " + "-" * 76)
    tot_pl = 0.0
    for r in rows:
        code = _from_code(r.get("code", ""))
        name = str(r.get("stock_name", ""))[:9]
        qty = float(r.get("qty", 0) or 0)
        cost = float(r.get("cost_price", 0) or 0)
        px = float(r.get("nominal_price", 0) or 0)
        mval = float(r.get("market_val", 0) or 0)
        pl = float(r.get("pl_val", 0) or 0)
        plr = float(r.get("pl_ratio", 0) or 0)
        tot_pl += pl
        print(f"  {code:<7}{name:<10}{qty:>9.4f}{cost:>11.2f}{px:>11.2f}"
              f"{mval:>11.2f}{pl:>+10.2f}{plr:>+8.2f}%")
    print("  " + "-" * 76)
    print(f"  持仓合计盈亏: ${_fmt(tot_pl)}")


def run_once(which: str) -> None:
    from futu import OpenSecTradeContext, TrdMarket, SecurityFirm, TrdEnv
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n富途账户速览  {stamp}  (网关 {HOST}:{PORT})\n")
    ctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=HOST,
                              port=PORT, security_firm=SecurityFirm.FUTUSECURITIES)
    try:
        if which in ("both", "paper"):
            show_account(ctx, TrdEnv.SIMULATE, "🧪 模拟盘 (SIMULATE · 假钱真流程)")
        if which in ("both", "real"):
            show_account(ctx, TrdEnv.REAL, "💰 实盘 (REAL · 真金账户)")
    finally:
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="富途账户速览 (只读)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--paper", action="store_true", help="只看模拟盘")
    g.add_argument("--real", action="store_true", help="只看实盘")
    ap.add_argument("--loop", type=int, default=0, metavar="秒",
                    help="每 N 秒自动刷新 (Ctrl+C 退出)")
    args = ap.parse_args()
    which = "paper" if args.paper else ("real" if args.real else "both")

    try:
        if args.loop and args.loop > 0:
            while True:
                try:
                    os.system("cls" if os.name == "nt" else "clear")
                except Exception:
                    pass
                run_once(which)
                print(f"\n(每 {args.loop} 秒刷新, 按 Ctrl+C 退出)")
                import time
                time.sleep(args.loop)
        else:
            run_once(which)
        return 0
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0
    except Exception as e:
        print("\n❌ 连接富途失败:", repr(e))
        print("请确认 FutuOpenD 网关已启动并登录 (默认 127.0.0.1:11111)。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
