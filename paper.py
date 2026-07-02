"""AI 交易员 · 模拟账户 (paper.py)
================================
把量化信号变成一个"会自己每天决策、持仓、算盈亏"的虚拟账户:

  - 起始虚拟资金 (默认 $100,000)
  - 每次运行按综合分自动调仓:
      综合分 ≥ 58  → 建/加仓到"建议仓位%"(单票上限 25%)
      45 ~ 58     → 维持不动 (持有)
      < 45        → 清仓 (减仓/卖出信号)
  - 记录每一笔成交 (含理由)、每日总资产快照 (盈亏曲线)
  - 持久化到本地 JSON, 可下载备份 / 上传恢复

设计为纯函数 + 一个状态字典, 方便在 Streamlit 里调用, 也可被 CI 每日跑。
不构成投资建议, 全部为历史/模拟演示。
"""
from __future__ import annotations

import json
import os
import datetime as dt

# 默认参数
START_CASH = 100_000.0
MAX_WEIGHT = 0.25          # 单票上限 25%
INVEST_CAP = 0.95          # 最多投入 95%, 留 5% 现金缓冲
BUY_SCORE = 58             # ≥ 建/加仓
EXIT_SCORE = 45            # < 清仓
MIN_TRADE = 50.0           # 小于这个金额的调仓忽略, 免得频繁碎单

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "paper_account.json")


# ---------------------------------------------------------------- 账户读写
def new_account(cash: float = START_CASH) -> dict:
    return {
        "cash": float(cash),
        "start_cash": float(cash),
        "positions": {},          # code -> {"shares":x, "avg_cost":y, "name":n}
        "trades": [],             # 成交流水
        "equity_curve": [],       # [{"date","total","cash","invested"}]
        "created": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "last_run": None,
    }


def load_account(path: str = _DEFAULT_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            acc = json.load(f)
        # 兼容旧结构
        acc.setdefault("positions", {})
        acc.setdefault("trades", [])
        acc.setdefault("equity_curve", [])
        acc.setdefault("start_cash", acc.get("cash", START_CASH))
        return acc
    except Exception:
        return new_account()


def save_account(acc: dict, path: str = _DEFAULT_PATH) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(acc, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- 估值
def _price_of(info: dict) -> float | None:
    try:
        return float(info["df"].iloc[-1]["Close"])
    except Exception:
        return None


def mark_to_market(acc: dict, detail: dict) -> dict:
    """按最新价重算持仓市值/盈亏, 返回 {invested, total, rows:[...]}。"""
    rows, invested = [], 0.0
    for code, pos in acc["positions"].items():
        info = detail.get(code)
        price = _price_of(info) if info else None
        shares = pos["shares"]
        avg = pos["avg_cost"]
        if price is None:
            price = avg           # 取不到价就用成本价, 避免炸
        mv = shares * price
        invested += mv
        pnl = (price - avg) * shares
        pnl_pct = (price / avg - 1) * 100 if avg > 0 else 0
        rows.append({
            "代码": code, "名称": pos.get("name", ""),
            "股数": round(shares, 2), "成本价": round(avg, 2),
            "现价": round(price, 2), "市值": round(mv, 2),
            "浮动盈亏": round(pnl, 2), "盈亏%": round(pnl_pct, 1),
        })
    total = acc["cash"] + invested
    rows.sort(key=lambda r: r["市值"], reverse=True)
    return {"invested": invested, "total": total, "rows": rows}


# ---------------------------------------------------------------- 决策 + 成交
def _target_weights(detail: dict, acc: dict) -> dict:
    """按综合分给出目标权重 (占总资产比例)。"""
    mtm = mark_to_market(acc, detail)
    total = mtm["total"] or acc["cash"]
    targets = {}
    # 当前权重 (用于 hold 区间保持不变)
    cur_w = {r["代码"]: (r["市值"] / total if total else 0) for r in mtm["rows"]}

    for code, info in detail.items():
        score = float(info.get("score", 0) or 0)
        plan = info.get("plan", {}) or {}
        if score >= BUY_SCORE:
            sug = float(plan.get("建议仓位%", 0) or 0) / 100.0
            if sug <= 0:
                sug = 0.10
            targets[code] = min(sug, MAX_WEIGHT)
        elif score < EXIT_SCORE:
            targets[code] = 0.0
        else:
            targets[code] = cur_w.get(code, 0.0)   # 持有: 维持现状

    # 清仓当前持有但本轮没数据的标的 (取不到行情)
    for code in acc["positions"]:
        targets.setdefault(code, 0.0)

    # 缩放: 目标总权重不超过 INVEST_CAP
    tot_w = sum(targets.values())
    if tot_w > INVEST_CAP and tot_w > 0:
        k = INVEST_CAP / tot_w
        targets = {c: w * k for c, w in targets.items()}
    return targets, mtm


def rebalance(acc: dict, detail: dict, names: dict | None = None,
              reason_regime: str = "") -> list[dict]:
    """按目标权重生成并执行调仓。返回本次成交列表。"""
    names = names or {}
    targets, mtm = _target_weights(detail, acc)
    total = mtm["total"] or acc["cash"]
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    exec_trades = []

    # 先卖后买, 保证现金充足
    def price_for(code):
        return _price_of(detail.get(code)) if detail.get(code) else None

    # 目标市值
    tgt_mv = {c: w * total for c, w in targets.items()}

    # 卖出 / 减仓
    for code, pos in list(acc["positions"].items()):
        price = price_for(code) or pos["avg_cost"]
        cur_mv = pos["shares"] * price
        want = tgt_mv.get(code, 0.0)
        if cur_mv - want > MIN_TRADE:
            sell_mv = cur_mv - want
            sell_sh = min(pos["shares"], sell_mv / price) if price > 0 else 0
            if sell_sh <= 0:
                continue
            acc["cash"] += sell_sh * price
            pnl = (price - pos["avg_cost"]) * sell_sh
            pos["shares"] -= sell_sh
            info = detail.get(code, {})
            sc = info.get("score")
            act = "清仓" if want <= 0 else "减仓"
            rsn = f"综合分 {sc} < {EXIT_SCORE}, {act}" if (sc is not None and sc < EXIT_SCORE) \
                  else f"再平衡{act}至目标权重 {targets.get(code,0)*100:.0f}%"
            t = {"date": stamp, "code": code, "name": pos.get("name", names.get(code, "")),
                 "side": "SELL", "shares": round(sell_sh, 3), "price": round(price, 2),
                 "amount": round(sell_sh * price, 2), "pnl": round(pnl, 2), "reason": rsn}
            acc["trades"].append(t); exec_trades.append(t)
            if pos["shares"] <= 1e-6:
                acc["positions"].pop(code, None)

    # 买入 / 加仓
    for code, want in sorted(tgt_mv.items(), key=lambda kv: -kv[1]):
        if want <= 0:
            continue
        price = price_for(code)
        if not price or price <= 0:
            continue
        pos = acc["positions"].get(code)
        cur_mv = (pos["shares"] * price) if pos else 0.0
        buy_mv = want - cur_mv
        if buy_mv < MIN_TRADE:
            continue
        buy_mv = min(buy_mv, acc["cash"])       # 现金约束
        if buy_mv < MIN_TRADE:
            continue
        buy_sh = buy_mv / price
        # 更新持仓 (加权平均成本)
        if pos:
            new_sh = pos["shares"] + buy_sh
            pos["avg_cost"] = (pos["avg_cost"] * pos["shares"] + price * buy_sh) / new_sh
            pos["shares"] = new_sh
        else:
            acc["positions"][code] = {"shares": buy_sh, "avg_cost": price,
                                      "name": names.get(code, "")}
        acc["cash"] -= buy_mv
        info = detail.get(code, {})
        sc = info.get("score")
        rsn = f"综合分 {sc} ≥ {BUY_SCORE}, 建/加仓至 {targets.get(code,0)*100:.0f}%"
        if reason_regime:
            rsn += f"({reason_regime})"
        t = {"date": stamp, "code": code, "name": names.get(code, ""),
             "side": "BUY", "shares": round(buy_sh, 3), "price": round(price, 2),
             "amount": round(buy_mv, 2), "pnl": 0.0, "reason": rsn}
        acc["trades"].append(t); exec_trades.append(t)

    # 记录当日快照
    mtm2 = mark_to_market(acc, detail)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    acc["equity_curve"] = [p for p in acc["equity_curve"] if p.get("date") != today]
    acc["equity_curve"].append({
        "date": today, "total": round(mtm2["total"], 2),
        "cash": round(acc["cash"], 2), "invested": round(mtm2["invested"], 2)})
    acc["last_run"] = stamp
    return exec_trades


def summary(acc: dict, detail: dict) -> dict:
    mtm = mark_to_market(acc, detail)
    total = mtm["total"]
    start = acc.get("start_cash", START_CASH)
    ret_pct = (total / start - 1) * 100 if start else 0
    return {
        "total": total, "cash": acc["cash"], "invested": mtm["invested"],
        "start": start, "ret_pct": ret_pct, "rows": mtm["rows"],
        "n_pos": len(acc["positions"]), "n_trades": len(acc["trades"]),
    }
