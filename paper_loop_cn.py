#!/usr/bin/env python3
"""A股本地虚拟盘 常驻自动交易 (paper_loop_cn.py)
=================================================

一直挂着运行。A股交易时段内, 每个交易日自动按综合分给【本地A股虚拟盘】
调仓一次, 账户状态写到 state/paper_account_cn.json。

注意: 这不是富途官方 SIMULATE 账户, 也不会向券商下单。A股用本地 JSON
虚拟成交, 行情仍走 engine/quotes: 本地有 FutuOpenD 时优先富途行情, 否则回退 yfinance。

环境变量:
  CN_PAPER_START_CASH  新账户起始资金, 默认 30000
  CN_LOOP_CHECK_SEC    多久醒来检查一次(秒), 默认 900
  CN_LOOP_REBAL_DAYS   两次调仓最少间隔(交易日), 默认 1

用法:
  python paper_loop_cn.py                    # 常驻运行
  python paper_loop_cn.py --once             # 只跑一轮(交易时段内)
  python paper_loop_cn.py --once --force     # 忽略交易时段/频率限制, 立刻跑
  python paper_loop_cn.py --once --force --dry  # 演算但不保存
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

import engine
import paper

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATE_DIR = os.path.join(_HERE, "state")
_ACCOUNT_PATH = os.path.join(_STATE_DIR, "paper_account_cn.json")
_LOOP_STATE_PATH = os.path.join(_STATE_DIR, "paper_loop_cn_state.json")
_LOG_PATH = os.path.join(_HERE, "paper_loop_cn.log")
_CN_TZ = ZoneInfo("Asia/Shanghai")

START_CASH = float(os.getenv("CN_PAPER_START_CASH", "30000") or 30000)
CHECK_SEC = int(float(os.getenv("CN_LOOP_CHECK_SEC", "10800") or 10800))
REBAL_DAYS = int(float(os.getenv("CN_LOOP_REBAL_DAYS", "1") or 1))
_last_wait_log = 0.0


def log(msg: str) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_loop_state() -> dict:
    try:
        with open(_LOOP_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_loop_state(st: dict) -> None:
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with open(_LOOP_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"写循环状态失败: {e!r}")


def _load_account() -> dict:
    if os.path.exists(_ACCOUNT_PATH):
        return paper.load_account(_ACCOUNT_PATH)
    return paper.new_account(START_CASH)


def market_open(now_cn: dt.datetime) -> bool:
    """A股常规交易时段: 周一至周五 09:30-11:30 / 13:00-15:00。不含节假日判断。"""
    if now_cn.weekday() >= 5:
        return False
    t = now_cn.time()
    return dt.time(9, 30) <= t <= dt.time(11, 30) or dt.time(13, 0) <= t <= dt.time(15, 0)


def _days_since(last_date_str: str, today_cn: dt.date) -> int:
    try:
        last = dt.date.fromisoformat(last_date_str)
        return (today_cn - last).days
    except Exception:
        return 10 ** 6


def _print_summary(acc: dict, detail: dict, trades: list[dict], dry: bool) -> None:
    summ = paper.summary(acc, detail)
    log(f"账户总资产 ¥{summ['total']:,.0f} ({summ['ret_pct']:+.1f}%) | "
        f"现金 ¥{summ['cash']:,.0f} | 持仓市值 ¥{summ['invested']:,.0f} | "
        f"持仓 {summ['n_pos']} 只")
    if dry:
        log("dry-run: 以上为演算结果, 未保存账户。")
    if trades:
        log("今日成交:")
        for t in trades:
            side = "买入" if t["side"] == "BUY" else "卖出"
            log(f"  {side} {t['code']} {t.get('name','')} "
                f"{t['shares']}股 @ ¥{t['price']} 金额 ¥{t['amount']:,.0f} | {t['reason']}")
    else:
        log("今日信号未触发调仓, 维持原持仓。")
    if summ["rows"]:
        log("当前持仓:")
        for r in summ["rows"]:
            log(f"  {r['代码']} {r['名称']} {r['股数']}股 市值 ¥{r['市值']:,.0f} "
                f"盈亏 {r['盈亏%']:+.1f}%")


def run_cycle(dry: bool = False) -> bool:
    """跑一轮A股本地虚拟盘调仓。成功拿到行情即返回 True。"""
    log("开始A股虚拟盘调仓: 拉取行情+计算信号中...")
    res = engine.analyze(
        engine.A_SHARE_WATCHLIST,
        period="2y",
        use_news=False,
        use_fundamentals=True,
        use_earnings=False,
        benchmark=engine.A_BENCHMARK,
        bench_label="沪深300",
    )
    detail = res.get("detail", {})
    if not detail:
        log("未取到A股行情, 本轮跳过。")
        return False

    regime = (res.get("regime", {}) or {}).get("label", "")
    log(f"已分析 {len(detail)} 只A股, 大盘环境: {regime or '未知'}, asof={res.get('asof')}")
    table = res.get("table")
    if table is not None and len(table):
        log(f"A股买入阈值: 综合分 >= {paper.BUY_SCORE}; 清仓阈值: 综合分 < {paper.EXIT_SCORE}")
        cols = [c for c in ["代码", "名称", "综合分", "信号", "建议仓位%", "现价"] if c in table.columns]
        for _, r in table[cols].head(8).iterrows():
            pos = r.get("建议仓位%", "")
            px = r.get("现价", "")
            log(f"  {r.get('代码','')} {r.get('名称','')} | "
                f"综合分 {r.get('综合分','')} | {r.get('信号','')} | "
                f"建议仓位 {pos}% | 现价 ¥{px}")

    acc = _load_account()
    work_acc = copy.deepcopy(acc) if dry else acc
    trades = paper.rebalance(work_acc, detail, names=engine.A_SHARE_WATCHLIST,
                             reason_regime=regime)
    if not dry:
        os.makedirs(_STATE_DIR, exist_ok=True)
        paper.save_account(work_acc, _ACCOUNT_PATH)
        log(f"账户已保存: {_ACCOUNT_PATH}")
    _print_summary(work_acc, detail, trades, dry=dry)
    return True


def maybe_rebalance(force: bool, dry: bool) -> None:
    global _last_wait_log
    now_cn = dt.datetime.now(_CN_TZ)
    today = now_cn.date()
    st = _load_loop_state()

    if not force:
        if not market_open(now_cn):
            if time.time() - _last_wait_log > min(CHECK_SEC, 300):
                log(f"等待A股交易时段中... 当前 {now_cn.strftime('%Y-%m-%d %H:%M:%S %Z')} "
                    "(交易时段 09:30-11:30 / 13:00-15:00)")
                _last_wait_log = time.time()
            return
        gap = _days_since(st.get("last_rebal_date", ""), today)
        if gap < REBAL_DAYS:
            if time.time() - _last_wait_log > min(CHECK_SEC, 300):
                log(f"今日已调仓({st.get('last_rebal_time', st.get('last_rebal_date'))}), 等待下个交易日。")
                _last_wait_log = time.time()
            return

    ok = run_cycle(dry=dry)
    if ok and not dry:
        st["last_rebal_date"] = today.isoformat()
        st["last_rebal_time"] = now_cn.strftime("%Y-%m-%d %H:%M %Z")
        _save_loop_state(st)


def main() -> int:
    ap = argparse.ArgumentParser(description="A股本地虚拟盘常驻自动交易")
    ap.add_argument("--once", action="store_true", help="只跑一轮就退出")
    ap.add_argument("--force", action="store_true", help="忽略交易时段/频率限制, 立刻跑")
    ap.add_argument("--dry", action="store_true", help="演算但不保存账户")
    args = ap.parse_args()

    log("=" * 56)
    log(f"A股本地虚拟盘自动交易启动 | 检查间隔={CHECK_SEC}s | "
        f"调仓间隔={REBAL_DAYS}交易日 | once={args.once} force={args.force} dry={args.dry}")
    log("说明: 本脚本只写本地虚拟账户, 不连接交易账户、不向券商下单。")

    if args.once:
        maybe_rebalance(force=args.force, dry=args.dry)
        log("单轮结束, 退出。")
        return 0

    try:
        while True:
            try:
                maybe_rebalance(force=args.force, dry=args.dry)
            except Exception as e:
                log(f"循环内异常(已忽略, 继续): {e!r}")
            time.sleep(CHECK_SEC)
    except KeyboardInterrupt:
        log("收到中断, 退出。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
