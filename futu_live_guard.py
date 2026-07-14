#!/usr/bin/env python3
"""富途实盘半自动控仓器 (futu_live_guard.py)
================================================

只按用户授权的固定规则管理现有美股实盘仓位:

- 只使用现有资产, 不入金、不融资、不期权、不买规则外新票。
- NVDA 作为核心仓: 目标 40%-50%, 低于 38% 才补, 高于 55% 才减。
- SPCX 最多 5%, 跌破 136 美元清掉。
- TSLA 若模型分低于 45 清掉。
- 单日最大成交金额 800 美元。
- 账户保留至少 8% 现金。
- 所有实盘订单先推送并进入待确认信箱, 确认后才执行。

默认只演算, 不下单:
  python futu_live_guard.py --dry-run

推送待确认单:
  python futu_live_guard.py --push

推送后等待确认并执行已批准订单:
  set FUTU_ALLOW_LIVE=1
  python futu_live_guard.py --push --wait

常驻执行器: 只执行你在手机/网页确认过的订单:
  set FUTU_ALLOW_LIVE=1
  python futu_live_guard.py --executor-loop

全部为风险控制工具, 不构成投资建议。
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import socket
import sys
import time

import engine
import notify
import orderstore
from futu_trader import FutuBroker, user_email as trader_user_email

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

NVDA_MIN = 0.38
NVDA_TARGET = 0.45
NVDA_MAX = 0.55
SPCX_MAX = 0.05
SPCX_STOP = 136.0
TSLA_EXIT_SCORE = 45.0
DAILY_TURNOVER_CAP = 800.0
CASH_RESERVE = 0.08
MIN_TRADE_USD = 20.0

# 买入白名单: 规则只允许补核心 NVDA, 不开新票。
BUY_ALLOW = {"NVDA"}
DEFAULT_USER_EMAIL = "zhaoqiuhao@zju.edu.cn"
DEFAULT_CONFIRM_URL = "http://127.0.0.1:8501/?confirm=1"


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _qty(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".")


def _from_futu_code(code: str) -> str:
    c = str(code or "")
    return c.split(".", 1)[1] if "." in c else c


def user_email() -> str:
    """待确认信箱账户。优先环境变量, 其次固定授权邮箱。"""
    return os.getenv("FUTU_USER_EMAIL", "").strip().lower() or DEFAULT_USER_EMAIL or trader_user_email()


def confirm_url() -> str:
    """邮件/微信里打开待确认页的链接。本机模式只能在同一台电脑上打开。"""
    env_url = os.getenv("BRAD_QUANT_CONFIRM_URL", "").strip()
    if env_url:
        return env_url
    try:
        cfg = notify.load_config()
        return (cfg.get("confirm_url")
                or (cfg.get("app", {}) or {}).get("confirm_url")
                or DEFAULT_CONFIRM_URL)
    except Exception:
        return DEFAULT_CONFIRM_URL


def worker_id() -> str:
    return os.getenv("BRAD_QUANT_WORKER_ID", "").strip() or f"{socket.gethostname()}:{os.getpid()}"


def read_real_account() -> tuple[float, dict]:
    """返回 (cash, positions). positions: ticker -> {shares, price, name, cost}."""
    from futu import OpenSecTradeContext, TrdMarket, SecurityFirm, TrdEnv, RET_OK

    host = os.getenv("FUTU_HOST", "127.0.0.1")
    port = int(os.getenv("FUTU_PORT", "11111"))
    ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US, host=host, port=port,
        security_firm=SecurityFirm.FUTUSECURITIES,
    )
    try:
        ret, acc = ctx.accinfo_query(trd_env=TrdEnv.REAL, currency="USD")
        if ret != RET_OK:
            raise RuntimeError(f"查询实盘资金失败: {acc}")
        a = acc.iloc[0]
        cash = float(a.get("us_cash", a.get("cash", 0)) or 0)

        ret, pos = ctx.position_list_query(trd_env=TrdEnv.REAL)
        if ret != RET_OK:
            raise RuntimeError(f"查询实盘持仓失败: {pos}")
        out = {}
        for _, r in pos.iterrows():
            shares = float(r.get("qty", 0) or 0)
            if shares <= 0:
                continue
            ticker = _from_futu_code(r.get("code", ""))
            out[ticker] = {
                "shares": shares,
                "price": float(r.get("nominal_price", 0) or 0),
                "cost": float(r.get("cost_price", 0) or 0),
                "name": str(r.get("stock_name", "") or ticker),
            }
        return cash, out
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def analyze_positions(positions: dict) -> dict:
    wl = {t: p.get("name", t) for t, p in positions.items()}
    if not wl:
        return {"detail": {}, "table": None, "asof": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    return engine.analyze(wl, period="1y", use_news=False,
                          use_fundamentals=True, use_earnings=False)


def _add_order(orders: list[dict], side: str, ticker: str, name: str,
               qty: float, price: float, reason: str, turnover_left: float) -> float:
    amount = abs(qty * price)
    if amount < MIN_TRADE_USD or price <= 0 or qty <= 0 or turnover_left <= 0:
        return turnover_left
    if amount > turnover_left:
        qty = math.floor((turnover_left / price) * 10000) / 10000
        amount = qty * price
    if amount < MIN_TRADE_USD or qty <= 0:
        return turnover_left
    orders.append({
        "side": side,
        "ticker": ticker,
        "name": name,
        "qty": round(qty, 4),
        "price": round(price, 2),
        "amount": round(amount, 2),
        "reason": reason,
    })
    return max(0.0, turnover_left - amount)


def build_guard_orders(cash: float, positions: dict, res: dict) -> tuple[list[dict], dict]:
    """按授权规则生成订单。返回 (orders, summary)。"""
    detail = res.get("detail", {}) or {}
    market_values = {
        t: float(p["shares"]) * float(p.get("price") or 0)
        for t, p in positions.items()
    }
    total = cash + sum(market_values.values())
    reserve = total * CASH_RESERVE
    turnover_left = DAILY_TURNOVER_CAP
    orders: list[dict] = []
    planned_cash = cash
    planned_mv = dict(market_values)

    def weight(t: str) -> float:
        return planned_mv.get(t, 0.0) / total if total > 0 else 0.0

    def sell(ticker: str, amount: float, reason: str) -> None:
        nonlocal turnover_left, planned_cash
        p = positions.get(ticker)
        if not p or amount <= 0 or turnover_left <= 0:
            return
        price = float(p.get("price") or 0)
        cur_mv = planned_mv.get(ticker, 0.0)
        amount = min(amount, cur_mv)
        qty = amount / price if price > 0 else 0
        before = turnover_left
        turnover_left = _add_order(
            orders, "SELL", ticker, p.get("name", ticker), qty, price, reason, turnover_left)
        executed = before - turnover_left
        planned_cash += executed
        planned_mv[ticker] = max(0.0, planned_mv.get(ticker, 0.0) - executed)

    def buy(ticker: str, amount: float, reason: str) -> None:
        nonlocal turnover_left, planned_cash
        if ticker not in BUY_ALLOW or ticker not in positions:
            return
        p = positions[ticker]
        price = float(p.get("price") or 0)
        max_cash = max(0.0, planned_cash - reserve)
        amount = min(amount, max_cash)
        qty = amount / price if price > 0 else 0
        before = turnover_left
        turnover_left = _add_order(
            orders, "BUY", ticker, p.get("name", ticker), qty, price, reason, turnover_left)
        executed = before - turnover_left
        planned_cash -= executed
        planned_mv[ticker] = planned_mv.get(ticker, 0.0) + executed

    # 1) 硬风险先处理: SPCX 止损 / TSLA 模型减仓。
    if "SPCX" in positions:
        spcx_px = float(positions["SPCX"].get("price") or 0)
        if spcx_px and spcx_px < SPCX_STOP:
            sell("SPCX", planned_mv.get("SPCX", 0.0),
                 f"授权规则: SPCX 跌破 ${SPCX_STOP:.0f}, 清仓")

    if "TSLA" in positions:
        score = float((detail.get("TSLA", {}) or {}).get("score", 0) or 0)
        if score < TSLA_EXIT_SCORE:
            sell("TSLA", planned_mv.get("TSLA", 0.0),
                 f"授权规则: TSLA 模型分 {score:.1f} < {TSLA_EXIT_SCORE:.0f}, 清仓")

    # 2) SPCX 最高 5%。
    if "SPCX" in positions and weight("SPCX") > SPCX_MAX:
        target_mv = total * SPCX_MAX
        sell("SPCX", planned_mv.get("SPCX", 0.0) - target_mv,
             f"授权规则: SPCX 仓位 {weight('SPCX')*100:.1f}% > 5%, 降至观察仓")

    # 3) NVDA 核心仓上下轨。
    if "NVDA" in positions:
        nvda_w = weight("NVDA")
        if nvda_w < NVDA_MIN:
            buy("NVDA", total * NVDA_TARGET - planned_mv.get("NVDA", 0.0),
                f"授权规则: NVDA 核心仓 {nvda_w*100:.1f}% < 38%, 补向 45%")
        elif nvda_w > NVDA_MAX:
            sell("NVDA", planned_mv.get("NVDA", 0.0) - total * 0.50,
                 f"授权规则: NVDA 仓位 {nvda_w*100:.1f}% > 55%, 降回 50%")

    # 4) 现金底线: 如果仍低于 8%, 按非 NVDA 弱票优先补现金。
    if planned_cash < reserve and turnover_left > 0:
        ranked = []
        for ticker, mv in planned_mv.items():
            if ticker == "NVDA" or mv <= 0:
                continue
            score = float((detail.get(ticker, {}) or {}).get("score", 50) or 50)
            ranked.append((score, ticker))
        for _, ticker in sorted(ranked):
            if planned_cash >= reserve or turnover_left <= 0:
                break
            sell(ticker, reserve - planned_cash,
                 f"授权规则: 现金低于 8%, 从弱势仓位补现金")

    summary = {
        "total": total,
        "cash": cash,
        "planned_cash": planned_cash,
        "reserve": reserve,
        "turnover_used": DAILY_TURNOVER_CAP - turnover_left,
        "turnover_cap": DAILY_TURNOVER_CAP,
        "weights_before": {t: (market_values[t] / total if total else 0) for t in market_values},
        "weights_after": {t: (planned_mv[t] / total if total else 0) for t in planned_mv},
    }
    return orders, summary


def build_message(orders: list[dict], summary: dict, res: dict) -> tuple[str, str]:
    asof = res.get("asof", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    title = f"皓量化实盘控仓待确认 {asof[:10]}"
    before = summary.get("weights_before", {})
    after = summary.get("weights_after", {})
    nvda_before = before.get("NVDA", 0.0) * 100
    nvda_after = after.get("NVDA", 0.0) * 100
    spcx_before = before.get("SPCX", 0.0) * 100
    spcx_after = after.get("SPCX", 0.0) * 100
    lines = [
        f"## 皓量化实盘控仓待确认",
        f"时间: {asof}",
        "",
        "### 判断标准",
        "- 只用现有资产, 不入金、不融资、不期权、不买规则外新票。",
        "- NVDA 是核心仓: 低于 38% 才补, 目标区间 40%-50%, 高于 55% 才减。",
        "- SPCX 最多 5%, 跌破 $136 清掉; TSLA 模型分低于 45 清掉。",
        "- 单日最大成交额 $800, 账户保留至少 8% 现金。",
        "",
        "### 今日解释",
        f"- NVDA 仓位约 {nvda_before:.1f}%, "
        + ("低于 38%, 所以小幅补仓。" if nvda_before < NVDA_MIN * 100 else
           "仍在核心仓规则范围内, 不强行加仓。"),
        f"- SPCX 仓位约 {spcx_before:.1f}%, "
        + ("超过 5%, 所以降到观察仓附近。" if spcx_before > SPCX_MAX * 100 else
           "未超过 5% 上限。"),
        "- TSLA 若模型分低于 45, 按授权规则清掉, 避免弱势票继续占用现金。",
        "",
        f"- 总资产: **{_fmt_money(summary['total'])}**",
        f"- 当前现金: **{_fmt_money(summary['cash'])}**",
        f"- 计划后现金: **{_fmt_money(summary['planned_cash'])}**",
        f"- 现金底线(8%): **{_fmt_money(summary['reserve'])}**",
        f"- 本次成交额: **{_fmt_money(summary['turnover_used'])} / {_fmt_money(summary['turnover_cap'])}**",
        f"- 计划后 NVDA/SPCX 仓位: **{nvda_after:.1f}% / {spcx_after:.1f}%**",
        "",
    ]
    if not orders:
        lines.append("当前无需调仓。")
    else:
        lines += [
            "| 方向 | 代码 | 数量 | 价格 | 金额 | 原因 |",
            "|---|---|---:|---:|---:|---|",
        ]
        for o in orders:
            side = "买入" if o["side"] == "BUY" else "卖出"
            lines.append(
                f"| {side} | **{o['ticker']}** | {_qty(o['qty'])} | "
                f"${o['price']:.2f} | ${o['amount']:,.2f} | {o['reason']} |")
    lines.append("")
    lines.append("### 如何确认")
    lines.append(f"打开确认页: {confirm_url()}")
    lines.append("也可以打开皓量化 App/网页 → 「📱 待确认」页, 对每笔订单点确认或拒绝。")
    lines.append("本机 local 模式下, 这个链接只适合在运行机器人的这台电脑上打开; 手机远程确认需要配置 Supabase/云端信箱。")
    lines.append("确认后, 电脑端执行器才会通过 Futu OpenD 提交到富途; 未确认不会下实盘单。")
    lines.append("")
    lines.append("> 仅按已授权规则控仓, 不入金、不融资、不期权。")
    md = "\n".join(lines)
    txt = md.replace("**", "")
    return title, md if orders else txt


def push_notice(title: str, body: str, send: bool) -> None:
    if not send:
        return
    _log(notify.send_wechat(title, body))
    _log(notify.send_email(title, body))


def create_pending_orders(orders: list[dict]) -> str | None:
    if not orders:
        return None
    email = user_email()
    existing = [
        r for r in orderstore.list_pending(email)
        if r.get("env") == "live_guard"
    ]
    if existing:
        today = dt.datetime.now().strftime("%Y-%m-%d")
        same_day = [
            r for r in existing
            if str(r.get("created_at", "")).startswith(today)
        ]
        if not same_day:
            for r in existing:
                orderstore.set_status(
                    r["id"], orderstore.STATUS_SKIPPED,
                    "被新的每日实盘控仓计划替代; 未执行")
            _log(f"已跳过 {len(existing)} 笔过期待确认单, 将创建新的每日计划。")
        else:
            batches = sorted({r.get("batch_id", "") for r in same_day if r.get("batch_id")})
            batch = batches[-1] if batches else None
            _log(f"今日已有 {len(same_day)} 笔实盘控仓待确认单, 不重复创建。"
                 + (f" 当前批次={batch}" if batch else ""))
            return batch
    existing = [
        r for r in orderstore.list_pending(email)
        if r.get("env") == "live_guard"
    ]
    if existing:
        batches = sorted({r.get("batch_id", "") for r in existing if r.get("batch_id")})
        batch = batches[-1] if batches else None
        _log(f"已有 {len(existing)} 笔实盘控仓待确认单, 不重复创建。"
             + (f" 当前批次={batch}" if batch else ""))
        return batch
    batch = orderstore.create_orders(email, orders, env="live_guard")
    _log(f"已写入待确认信箱: account={email}, batch={batch}")
    if not orderstore.using_supabase():
        _log("当前信箱后端为 local; 手机远程确认需配置 Supabase。")
    return batch


def _execute_rows(rows: list[dict], broker: FutuBroker, wid: str) -> int:
    n = 0
    for r in rows:
        if r.get("status") != orderstore.STATUS_APPROVED:
            continue
        desc = f"{r['side']} {_qty(float(r['qty']))}股 {r['ticker']} @ ${float(r['price']):.2f}"
        if not orderstore.claim_for_execution(r["id"], wid):
            _log(f"跳过: {desc} 已被其他执行器领取或状态已变化。")
            continue
        try:
            res = broker.place(r)
        except Exception as e:
            res = f"❌ 执行异常: {e}"
        ok = "❌" not in res
        orderstore.set_status(
            r["id"], orderstore.STATUS_DONE if ok else orderstore.STATUS_FAILED, res)
        n += 1
        _log(f"确认后执行: {desc} -> {res}")
    return n


def execute_approved(batch: str, timeout_min: int) -> int:
    if os.getenv("FUTU_ALLOW_LIVE") != "1":
        _log("未执行: 需设置 FUTU_ALLOW_LIVE=1 才允许实盘下单。")
        return 2
    broker = FutuBroker("live")
    wid = worker_id()
    deadline = time.time() + timeout_min * 60
    try:
        broker.unlock_if_needed()
        while time.time() < deadline:
            rows = orderstore.get_batch(batch)
            approved = [
                r for r in rows
                if r.get("status") == orderstore.STATUS_APPROVED
            ]
            pending = [r for r in rows if r.get("status") == orderstore.STATUS_PENDING]
            _execute_rows(approved, broker, wid)
            if not pending and not approved:
                return 0
            time.sleep(10)
        _log(f"等待确认超时({timeout_min}分钟), 未确认订单保留在信箱。")
        return 0
    finally:
        broker.close()


def execute_approved_once() -> int:
    """执行当前用户所有已确认的 live_guard 订单, 只跑一轮。"""
    if os.getenv("FUTU_ALLOW_LIVE") != "1":
        _log("未执行: 需设置 FUTU_ALLOW_LIVE=1 才允许实盘下单。")
        return 2
    email = user_email()
    rows = orderstore.list_approved(email, env="live_guard")
    if not rows:
        return 0
    _log(f"发现 {len(rows)} 笔已确认待执行订单: account={email}, backend={orderstore.backend_name()}")
    broker = FutuBroker("live")
    try:
        broker.unlock_if_needed()
        n = _execute_rows(rows, broker, worker_id())
        _log(f"本轮执行完成: {n}/{len(rows)} 笔。")
        return 0
    finally:
        broker.close()


def executor_loop(poll_sec: int) -> int:
    """常驻轮询云端/本地信箱, 只执行用户已确认的 live_guard 订单。"""
    if os.getenv("FUTU_ALLOW_LIVE") != "1":
        _log("未启动执行器: 需设置 FUTU_ALLOW_LIVE=1 才允许实盘下单。")
        return 2
    _log(f"实盘执行器启动: account={user_email()}, backend={orderstore.backend_name()}, poll={poll_sec}s")
    while True:
        execute_approved_once()
        time.sleep(max(5, poll_sec))


def print_orders(orders: list[dict], summary: dict) -> None:
    _log(f"总资产 {_fmt_money(summary['total'])}, 当前现金 {_fmt_money(summary['cash'])}, "
         f"计划后现金 {_fmt_money(summary['planned_cash'])}")
    _log(f"成交额 {_fmt_money(summary['turnover_used'])} / {_fmt_money(summary['turnover_cap'])}")
    if not orders:
        _log("当前无需调仓。")
        return
    _log("拟订单:")
    for o in orders:
        side = "买入" if o["side"] == "BUY" else "卖出"
        _log(f"  {side} {o['ticker']} {_qty(o['qty'])}股 @ ${o['price']:.2f} "
             f"金额 ${o['amount']:,.2f} | {o['reason']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="富途实盘半自动控仓器")
    ap.add_argument("--dry-run", action="store_true", help="只演算并打印, 不写信箱")
    ap.add_argument("--push", action="store_true", help="写入待确认信箱并推送微信/邮件")
    ap.add_argument("--wait", action="store_true", help="写信箱后等待确认, 执行批准订单")
    ap.add_argument("--execute-batch", metavar="BATCH_ID",
                    help="执行某批次中已经批准的订单; 需 FUTU_ALLOW_LIVE=1")
    ap.add_argument("--execute-approved", action="store_true",
                    help="执行当前用户所有已确认的实盘控仓订单; 需 FUTU_ALLOW_LIVE=1")
    ap.add_argument("--executor-loop", action="store_true",
                    help="常驻轮询已确认订单并执行; 需 FUTU_ALLOW_LIVE=1")
    ap.add_argument("--poll-sec", type=int, default=20, help="常驻执行器轮询间隔秒数")
    ap.add_argument("--no-notify", action="store_true", help="不发送微信/邮件")
    ap.add_argument("--timeout-min", type=int, default=30, help="等待确认分钟数")
    args = ap.parse_args()

    if args.execute_batch:
        return execute_approved(args.execute_batch, timeout_min=args.timeout_min)
    if args.execute_approved:
        return execute_approved_once()
    if args.executor_loop:
        return executor_loop(args.poll_sec)

    cash, positions = read_real_account()
    res = analyze_positions(positions)
    orders, summary = build_guard_orders(cash, positions, res)
    print_orders(orders, summary)
    title, body = build_message(orders, summary, res)

    if not args.push:
        _log("\n未写入信箱。加 --push 才会通知并等待确认。")
        return 0

    batch = create_pending_orders(orders)
    push_notice(title, body, send=(not args.no_notify))
    if args.wait and batch:
        return execute_approved(batch, timeout_min=args.timeout_min)
    return 0


if __name__ == "__main__":
    _rc = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(_rc if isinstance(_rc, int) else 0)
