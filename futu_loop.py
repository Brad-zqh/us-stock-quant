"""富途模拟盘 常驻自动交易 (futu_loop.py)
=========================================
一直挂着运行。美股常规交易时段内, 每个交易日自动按综合分给【模拟盘 SIMULATE】
调仓一次 (先卖后买, 整数股)。小资金适配:
  - 预算锁 FUTU_BUDGET (默认 3600 美元, 只动这么多钱, 不满仓模拟盘的 100 万)
  - 最多持 FUTU_MAX_POSITIONS 只 (默认 4)
  - 再平衡死区 FUTU_REBAL_BAND (默认 0.03), 偏离小于死区不动, 省手续费/降频

只下模拟盘 (假钱真流程), 默认绝不碰实盘。OpenD 网关没开/连不上时会自动跳过并稍后重试。

环境变量 (都有默认值, 一般不用改):
  FUTU_BUDGET          投入预算上限美元, 默认 3600
  FUTU_MAX_POSITIONS   最多持仓只数, 默认 4
  FUTU_REBAL_BAND      再平衡死区(占总资产比例), 默认 0.03
  LOOP_CHECK_SEC       多久醒来检查一次(秒), 默认 900 (15分钟)
  LOOP_REBAL_DAYS      两次调仓最少间隔(交易日), 默认 1 (每个交易日一次; 设 7 约周频)
  LOOP_MODE            paper(默认) / dry(只演算不下单) / live(实盘, 需另设 FUTU_ALLOW_LIVE=1)

用法:
  python futu_loop.py               # 常驻运行 (给计划任务/桌面脚本调用)
  python futu_loop.py --once        # 只跑一轮就退出 (交易时段内)
  python futu_loop.py --once --force # 忽略交易时段/频率限制, 立刻跑一轮 (测试用)
  python futu_loop.py --once --force --dry  # 立刻演算一轮但不下单 (最安全的测试)
"""
from __future__ import annotations

# --- 先设小资金默认值, 必须在 import futu_trader 之前 (它 import 时就读这些) ---
import os
os.environ.setdefault("FUTU_BUDGET", "3600")
os.environ.setdefault("FUTU_MAX_POSITIONS", "4")
os.environ.setdefault("FUTU_REBAL_BAND", "0.03")

import argparse
import datetime as dt
import json
import logging
import sys
import time
from zoneinfo import ZoneInfo

logging.disable(logging.WARNING)  # 压掉 futu SDK 的 INFO 日志

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATE_DIR = os.path.join(_HERE, "state")
_STATE_PATH = os.path.join(_STATE_DIR, "futu_loop_state.json")
_LOG_PATH = os.path.join(_HERE, "futu_loop.log")
_ET = ZoneInfo("America/New_York")

CHECK_SEC = int(float(os.getenv("LOOP_CHECK_SEC", "900") or 900))
REBAL_DAYS = int(float(os.getenv("LOOP_REBAL_DAYS", "1") or 1))
LOOP_MODE = os.getenv("LOOP_MODE", "paper").strip().lower()


def log(msg: str) -> None:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_state() -> dict:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"写状态失败: {e!r}")


def market_open(now_et: dt.datetime) -> bool:
    """美股常规交易时段: 周一至周五 09:30-16:00 (美东)。不含节假日判断。"""
    if now_et.weekday() >= 5:  # 周六日
        return False
    t = now_et.time()
    return dt.time(9, 30) <= t <= dt.time(16, 0)


def _days_since(last_date_str: str, today_et: dt.date) -> int:
    try:
        last = dt.date.fromisoformat(last_date_str)
        return (today_et - last).days
    except Exception:
        return 10 ** 6  # 没有记录 -> 视为很久以前, 允许调仓


def run_cycle(mode: str) -> bool:
    """跑一轮调仓。返回 True 表示成功执行了一轮(可标记今日已调仓); False 表示连接失败等, 稍后重试。"""
    import futu_trader as ft
    log(f"开始调仓 (mode={mode}, 预算=${os.getenv('FUTU_BUDGET')}, "
        f"最多持仓={os.getenv('FUTU_MAX_POSITIONS')})")
    try:
        rc = ft.run(mode, auto=(mode == "paper"), push=False)
        # rc: 0 正常(含无单可下); 3 连接富途失败; 2 实盘被禁用; 1 无行情
        if rc == 3:
            log("⚠️ 连接 FutuOpenD 失败, 稍后重试。请确认网关已启动登录。")
            return False
        if rc == 1:
            log("⚠️ 未取到行情, 稍后重试。")
            return False
        log(f"本轮完成 (rc={rc})。")
        return True
    except Exception as e:
        log(f"❌ 本轮异常: {e!r}")
        return False


def maybe_rebalance(force: bool, mode: str) -> None:
    now_et = dt.datetime.now(_ET)
    today = now_et.date()
    st = _load_state()

    if not force:
        if not market_open(now_et):
            return
        gap = _days_since(st.get("last_rebal_date", ""), today)
        if gap < REBAL_DAYS:
            return  # 本周期已调过, 未到下次

    ok = run_cycle(mode)
    if ok and mode != "dry":
        st["last_rebal_date"] = today.isoformat()
        st["last_rebal_time"] = now_et.strftime("%Y-%m-%d %H:%M %Z")
        _save_state(st)


def main() -> int:
    ap = argparse.ArgumentParser(description="富途模拟盘常驻自动交易")
    ap.add_argument("--once", action="store_true", help="只跑一轮就退出")
    ap.add_argument("--force", action="store_true", help="忽略交易时段/频率限制, 立刻跑")
    ap.add_argument("--dry", action="store_true", help="演算但不下单 (mode=dry)")
    args = ap.parse_args()

    mode = "dry" if args.dry else LOOP_MODE
    if mode not in ("paper", "dry", "live"):
        mode = "paper"

    log("=" * 56)
    log(f"富途模拟盘自动交易启动 | mode={mode} | 检查间隔={CHECK_SEC}s | "
        f"调仓间隔={REBAL_DAYS}交易日 | once={args.once} force={args.force}")
    if mode == "live":
        log("⚠️ 实盘模式! 需要 FUTU_ALLOW_LIVE=1 且交易解锁, 风险自负。")

    if args.once:
        maybe_rebalance(force=args.force, mode=mode)
        log("单轮结束, 退出。")
        return 0

    # 常驻循环
    try:
        while True:
            try:
                maybe_rebalance(force=args.force, mode=mode)
            except Exception as e:
                log(f"循环内异常(已忽略, 继续): {e!r}")
            time.sleep(CHECK_SEC)
    except KeyboardInterrupt:
        log("收到中断, 退出。")
        return 0


if __name__ == "__main__":
    _rc = main()
    # 富途 SDK 会起非守护后台线程, sys.exit 无法结束进程 -> 强制退出(仅 --once 会走到这)
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(_rc if isinstance(_rc, int) else 0)
