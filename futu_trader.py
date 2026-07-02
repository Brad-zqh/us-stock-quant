#!/usr/bin/env python3
"""
富途自动/半自动交易机器人 · 美股 (futu_trader.py)
================================================
在你自己的电脑上运行 (Windows / Mac), 连接本地 FutuOpenD 网关, 把量化信号
自动/半自动地下到富途账户。默认走 **模拟盘 (SIMULATE, 假钱真流程)**, 安全第一。

设计原则:
  - 与 paper.py 用同一套决策阈值 (综合分 ≥58 买 / <45 清 / 单票 ≤25%),
    所以「模拟盘机器人」和你看到的 AI 交易员模拟账户逻辑完全一致。
  - 只做美股 (US.*); A股富途 OpenAPI 不支持程序化下单, 本脚本不涉及。
  - 真金实盘默认禁用, 必须显式 --live 且设环境变量 FUTU_ALLOW_LIVE=1, 且强制逐笔确认。

运行模式:
  python futu_trader.py --dry-run           # 【今天就能跑, 无需富途】只算信号+打印拟下单
  python futu_trader.py --paper             # 连 FutuOpenD, 模拟盘下单 (默认逐笔确认)
  python futu_trader.py --paper --yes       # 模拟盘全自动 (不逐笔问)
  python futu_trader.py --live              # 真实盘 (需 FUTU_ALLOW_LIVE=1, 强制逐笔确认)

前置 (仅 --paper / --live 需要, 见 futu 环境搭建说明):
  1. 装富途牛牛 + 开通 OpenAPI 权限
  2. 本地跑 FutuOpenD 网关 (默认 127.0.0.1:11111), 登录你的账号
  3. pip install futu-api

环境变量 (都可选, 有默认):
  FUTU_HOST        FutuOpenD 地址, 默认 127.0.0.1
  FUTU_PORT        端口, 默认 11111
  FUTU_TRADE_PWD   交易解锁密码 (实盘下单需要; 模拟盘一般不需要)
  FUTU_ALLOW_LIVE  设为 1 才允许 --live 真金下单
  FUTU_WATCHLIST   自定义美股池, 逗号分隔如 "AAPL,NVDA,TSLA"; 缺省用 engine 默认池

全部为工具, 不构成投资建议。实盘有风险, 后果自负。
"""
from __future__ import annotations

import os
import sys
import math
import time
import argparse
import datetime as dt

import engine
import paper       # 复用决策阈值与取价工具, 保证与模拟账户逻辑一致
import orderstore  # 手机端半自动确认的"信箱" (Supabase / 本地 JSON)

# Windows 控制台默认 gbk 打不出 emoji/中文, 统一 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_ORDER_USD = 50.0        # 小于此金额的调仓忽略, 免碎单
DEFAULT_START_CASH = 100_000.0


# ---------------------------------------------------------------- 工具
def _log(msg: str = "") -> None:
    print(msg, flush=True)


def get_watchlist() -> dict:
    """美股池: 环境变量 FUTU_WATCHLIST 优先, 否则用 engine 默认池。"""
    raw = os.getenv("FUTU_WATCHLIST", "").strip()
    if raw:
        return {c.strip().upper(): c.strip().upper() for c in raw.split(",") if c.strip()}
    return dict(engine.DEFAULT_WATCHLIST)


def to_futu_code(ticker: str) -> str:
    """本地美股代码 -> 富途代码 (AAPL -> US.AAPL)。"""
    t = ticker.strip().upper()
    return t if t.startswith("US.") else f"US.{t}"


def from_futu_code(code: str) -> str:
    return code.split(".", 1)[1] if code.startswith("US.") else code


# ---------------------------------------------------------------- 决策: 信号 -> 目标持仓
def compute_target_weights(detail: dict, positions: dict) -> dict:
    """按综合分给出每只票的目标权重 (占总资产比例)。与 paper.py 同规则:
       ≥58 买到建议仓位%(单票上限25%); <45 清仓; 中间维持现状。
       positions: {ticker: shares}  用于 hold 区间保持当前权重。
       返回 {ticker: weight}; weight=None 表示"维持不动(hold)"。
    """
    targets: dict[str, float | None] = {}
    for code, info in detail.items():
        score = float(info.get("score", 0) or 0)
        plan = info.get("plan", {}) or {}
        if score >= paper.BUY_SCORE:
            sug = float(plan.get("建议仓位%", 0) or 0) / 100.0
            if sug <= 0:
                sug = 0.10
            targets[code] = min(sug, paper.MAX_WEIGHT)
        elif score < paper.EXIT_SCORE:
            targets[code] = 0.0
        else:
            targets[code] = None   # hold
    # 持有中但本轮无数据的票 -> 清仓 (取不到价, 保守离场)
    for t in positions:
        targets.setdefault(t, 0.0)

    # 缩放: 明确的目标权重之和不超过 INVEST_CAP (hold 的不参与缩放)
    explicit = {c: w for c, w in targets.items() if isinstance(w, (int, float))}
    tot = sum(explicit.values())
    if tot > paper.INVEST_CAP and tot > 0:
        k = paper.INVEST_CAP / tot
        for c in explicit:
            targets[c] = explicit[c] * k
    return targets


def price_of(detail: dict, ticker: str) -> float | None:
    return paper._price_of(detail.get(ticker)) if detail.get(ticker) else None


def build_orders(detail: dict, cash: float, positions: dict) -> list[dict]:
    """对比目标持仓与当前持仓, 生成买卖单列表 (整数股)。
       positions: {ticker: {"shares":x, "price":p}}  (price 可为 None)
    """
    pos_shares = {t: float(p.get("shares", 0) or 0) for t, p in positions.items()}
    # 当前总资产 = 现金 + 各持仓市值 (用最新价)
    invested = 0.0
    for t, sh in pos_shares.items():
        px = price_of(detail, t) or positions[t].get("price") or 0
        invested += sh * (px or 0)
    total = cash + invested
    if total <= 0:
        total = cash or DEFAULT_START_CASH

    targets = compute_target_weights(detail, pos_shares)
    orders: list[dict] = []

    # 先卖后买, 释放现金
    sells, buys = [], []
    for code, weight in targets.items():
        if weight is None:
            continue  # hold
        px = price_of(detail, code)
        if not px or px <= 0:
            # 没价格又要清仓的, 记为需人工处理 (跳过自动)
            continue
        cur_sh = pos_shares.get(code, 0.0)
        cur_mv = cur_sh * px
        tgt_mv = weight * total
        diff = tgt_mv - cur_mv
        name = engine.DEFAULT_WATCHLIST.get(code, "")
        info = detail.get(code, {})
        score = info.get("score")
        if diff < -MIN_ORDER_USD and cur_sh > 0:
            qty = min(cur_sh, math.floor((-diff) / px))
            if qty >= 1:
                act = "清仓" if weight <= 0 else "减仓"
                sells.append({"side": "SELL", "ticker": code, "name": name,
                              "qty": int(qty), "price": round(px, 2),
                              "amount": round(qty * px, 2), "score": score,
                              "reason": f"综合分{score}, {act}至目标{weight*100:.0f}%"})
        elif diff > MIN_ORDER_USD:
            buys.append({"side": "BUY", "ticker": code, "name": name,
                         "price": round(px, 2), "want_usd": diff, "score": score,
                         "reason": f"综合分{score}≥{paper.BUY_SCORE}, 建/加仓至{weight*100:.0f}%"})

    orders.extend(sells)
    # 买入按现金约束依次分配 (分高的先买)
    avail = cash + sum(o["amount"] for o in sells)
    for o in sorted(buys, key=lambda x: -(x.get("score") or 0)):
        px = o["price"]
        spend = min(o["want_usd"], avail)
        qty = math.floor(spend / px)
        if qty >= 1:
            amt = qty * px
            avail -= amt
            orders.append({"side": "BUY", "ticker": o["ticker"], "name": o["name"],
                           "qty": int(qty), "price": px, "amount": round(amt, 2),
                           "score": o["score"], "reason": o["reason"]})
    return orders


def print_orders(orders: list[dict], cash: float, total: float, env_label: str) -> None:
    _log(f"\n===== 拟下单 ({env_label}) =====")
    _log(f"账户现金 ${cash:,.0f}　总资产 ${total:,.0f}")
    if not orders:
        _log("今日无调仓信号, 维持现有持仓观望。")
        return
    _log(f"{'方向':<5}{'代码':<8}{'股数':>7}{'价格':>10}{'金额':>12}   理由")
    for o in orders:
        side = "🟢买入" if o["side"] == "BUY" else "🔴卖出"
        _log(f"{side:<5}{o['ticker']:<8}{o['qty']:>7}{o['price']:>10.2f}"
             f"{o['amount']:>12,.0f}   {o['reason']}")


# ---------------------------------------------------------------- 富途下单
class FutuBroker:
    """封装 FutuOpenD 交易上下文。仅 --paper/--live 时使用。"""

    def __init__(self, env: str):
        from futu import (OpenSecTradeContext, TrdMarket, SecurityFirm, TrdEnv)
        self._TrdEnv = TrdEnv
        self.env = TrdEnv.SIMULATE if env == "paper" else TrdEnv.REAL
        host = os.getenv("FUTU_HOST", "127.0.0.1")
        port = int(os.getenv("FUTU_PORT", "11111"))
        self.ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US, host=host, port=port,
            security_firm=SecurityFirm.FUTUSECURITIES)

    def unlock_if_needed(self) -> None:
        pwd = os.getenv("FUTU_TRADE_PWD", "")
        if self.env == self._TrdEnv.REAL and pwd:
            from futu import RET_OK
            ret, data = self.ctx.unlock_trade(pwd)
            if ret != RET_OK:
                raise RuntimeError(f"解锁交易失败: {data}")

    def cash(self) -> float:
        from futu import RET_OK
        ret, data = self.ctx.accinfo_query(trd_env=self.env)
        if ret != RET_OK:
            raise RuntimeError(f"查询资金失败: {data}")
        for col in ("us_cash", "cash", "avl_withdrawal_cash", "power"):
            if col in data.columns:
                try:
                    return float(data.iloc[0][col])
                except Exception:
                    continue
        return float(data.iloc[0].get("cash", DEFAULT_START_CASH))

    def positions(self) -> dict:
        from futu import RET_OK
        ret, data = self.ctx.position_list_query(trd_env=self.env)
        if ret != RET_OK:
            raise RuntimeError(f"查询持仓失败: {data}")
        out = {}
        for _, r in data.iterrows():
            t = from_futu_code(str(r.get("code", "")))
            qty = float(r.get("qty", 0) or 0)
            if qty > 0:
                out[t] = {"shares": qty, "price": float(r.get("nominal_price", 0) or 0) or None}
        return out

    def place(self, order: dict) -> str:
        from futu import RET_OK, TrdSide, OrderType
        side = TrdSide.BUY if order["side"] == "BUY" else TrdSide.SELL
        ret, data = self.ctx.place_order(
            price=order["price"], qty=order["qty"], code=to_futu_code(order["ticker"]),
            trd_side=side, order_type=OrderType.NORMAL, trd_env=self.env)
        if ret != RET_OK:
            return f"❌ 失败: {data}"
        try:
            oid = data.iloc[0].get("order_id", "")
        except Exception:
            oid = ""
        return f"✅ 已提交 (order_id={oid})"

    def close(self) -> None:
        try:
            self.ctx.close()
        except Exception:
            pass


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


# ---------------------------------------------------------------- 手机确认相关
def user_email() -> str:
    """本机机器人代表哪个用户往信箱写单。优先 FUTU_USER_EMAIL, 否则管理员邮箱, 再否则本地占位。"""
    e = os.getenv("FUTU_USER_EMAIL", "").strip().lower()
    if e:
        return e
    try:
        import userstore
        admins = sorted(userstore.admin_emails())
        if admins:
            return admins[0]
    except Exception:
        pass
    return "local@futu"


def _execute_order(broker, order: dict, mode: str) -> str:
    """真正下单 (paper/live); dry 模式无 broker, 仅演示。"""
    if broker is None:
        return "🧪 演示(未真正下单)"
    return broker.place(order)


def phone_confirm_flow(orders: list[dict], broker, mode: str, env_label: str,
                       poll_secs: int = 10, timeout_min: int = 30) -> int:
    """把拟下单推到信箱, 等手机端确认, 再执行被批准的单。"""
    email = user_email()
    if not orderstore.using_supabase():
        _log("\n⚠️ 未配置 Supabase, 手机端无法远程确认。已写入本地 orders.json 仅供本机测试。")
    batch = orderstore.create_orders(email, orders, env=mode)
    _log(f"\n📲 已把 {len(orders)} 笔拟下单推送到「待确认信箱」(账户 {email}, 批次 {batch})。")
    _log("   请打开手机 App →「📱 待确认」标签, 逐笔或一键 确认/拒绝。")
    _log(f"   本机将每 {poll_secs}s 轮询一次, 最长等待 {timeout_min} 分钟…")

    done_ids: set[str] = set()
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        rows = orderstore.get_batch(batch)
        pending = [r for r in rows if r.get("status") == orderstore.STATUS_PENDING]
        approved = [r for r in rows
                    if r.get("status") == orderstore.STATUS_APPROVED and r["id"] not in done_ids]

        for r in approved:
            desc = f"{r['side']} {r['qty']}股 {r['ticker']} @ ${r['price']}"
            res = _execute_order(broker, r, mode)
            ok = "❌" not in res
            orderstore.set_status(
                r["id"], orderstore.STATUS_DONE if ok else orderstore.STATUS_FAILED, res)
            done_ids.add(r["id"])
            _log(f"  ✅确认→执行: {desc} … {res}")

        if not pending and not approved:
            # 全部离开 pending/approved: 结束
            rejected = [r for r in rows if r.get("status") == orderstore.STATUS_REJECTED]
            _log(f"\n完成。执行 {len(done_ids)} 笔, 拒绝 {len(rejected)} 笔。")
            return 0
        time.sleep(poll_secs)

    _log(f"\n⏰ 等待超时({timeout_min}分钟)。未确认的单已留在信箱, 可稍后在手机处理或重跑。")
    return 0


def local_confirm_flow(orders: list[dict], broker, mode: str, auto: bool, env_label: str) -> int:
    """无手机确认时的本机流程: 命令行逐笔 y/n (dry 模式仅打印)。"""
    if broker is None:   # dry-run 无 push: 仅演示
        _log("\n(dry-run: 仅演示, 未连接富途、未下任何单)")
        return 0
    force_confirm = (mode == "live") or (not auto)
    if force_confirm and not auto:
        if not _confirm(f"\n确认在【{env_label}】执行以上 {len(orders)} 笔? 逐笔确认。"):
            _log("已取消, 未下单。")
            return 0
    for o in orders:
        desc = f"{o['side']} {o['qty']}股 {o['ticker']} @ ${o['price']}"
        if mode == "live" or (force_confirm and not auto):
            if not _confirm(f"→ {desc}?"):
                _log(f"  跳过 {desc}")
                continue
        _log(f"  {desc} … {broker.place(o)}")
    _log("\n完成。可在富途牛牛 App / 客户端查看订单与持仓。")
    return 0


# ---------------------------------------------------------------- 主流程
def run(mode: str, auto: bool, push: bool = False) -> int:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log(f"[{stamp}] 富途交易机器人启动 (mode={mode}, 自动={auto}, 手机确认={push})")

    wl = get_watchlist()
    _log(f"美股池: {', '.join(wl)}")
    _log("拉取行情+计算信号中… (约 10-30 秒)")
    res = engine.analyze(wl, period="1y", use_news=False, use_earnings=False)
    detail = res.get("detail", {})
    if not detail:
        _log("❌ 未取到行情, 退出。稍后重试。")
        return 1

    env_label = {"dry": "仅演算·未下单", "paper": "富途模拟盘 SIMULATE",
                 "live": "富途真实盘 REAL"}[mode]

    broker = None
    try:
        if mode in ("paper", "live"):
            if mode == "live" and os.getenv("FUTU_ALLOW_LIVE") != "1":
                _log("⛔ 实盘被禁用。真金下单需设环境变量 FUTU_ALLOW_LIVE=1 并了解风险后重试。")
                return 2
            try:
                broker = FutuBroker(mode)
            except ImportError:
                _log("❌ 未安装 futu-api。请先 `pip install futu-api` 并启动 FutuOpenD 网关。")
                return 3
            except Exception as e:
                _log(f"❌ 连接 FutuOpenD 失败: {e}\n"
                     f"请确认 FutuOpenD 已启动并登录 (默认 127.0.0.1:11111)。")
                return 3
            broker.unlock_if_needed()
            cash = broker.cash()
            positions = broker.positions()
            _log(f"已连接富途。现金 ${cash:,.0f}, 当前持仓 {len(positions)} 只: "
                 f"{', '.join(positions) or '无'}")
        else:  # dry
            cash = float(os.getenv("FUTU_START_CASH", DEFAULT_START_CASH))
            positions = {}

        orders = build_orders(detail, cash, positions)
        total = cash + sum(
            (price_of(detail, t) or (positions[t].get('price') or 0)) * positions[t]['shares']
            for t in positions)
        print_orders(orders, cash, total, env_label)
        if not orders:
            return 0

        if push:
            return phone_confirm_flow(orders, broker, mode, env_label)
        return local_confirm_flow(orders, broker, mode, auto, env_label)
    finally:
        if broker is not None:
            broker.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="富途美股 自动/半自动交易机器人")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="只演算+打印拟下单, 无需富途")
    g.add_argument("--paper", action="store_true", help="富途模拟盘下单 (假钱)")
    g.add_argument("--live", action="store_true", help="富途真实盘下单 (需 FUTU_ALLOW_LIVE=1)")
    ap.add_argument("--yes", action="store_true", help="不逐笔确认 (全自动, 仅模拟盘)")
    ap.add_argument("--push", action="store_true",
                    help="手机确认模式: 拟下单推到信箱, 手机 App 确认后本机执行 (需 Supabase)")
    args = ap.parse_args()

    if args.paper:
        mode = "paper"
    elif args.live:
        mode = "live"
    else:
        mode = "dry"

    auto = args.yes and mode == "paper"   # 实盘不允许全自动
    return run(mode, auto, push=args.push)


if __name__ == "__main__":
    sys.exit(main())
