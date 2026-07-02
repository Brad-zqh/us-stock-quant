#!/usr/bin/env python3
"""
AI 交易员 · 每日自动运行 (run_ai_trader.py)
==========================================
被 GitHub Actions 每个交易日收盘后调用, 完成一条龙:

  1. 分析自选股 (engine.analyze)
  2. 模拟账户按综合分自动调仓 (paper.rebalance)
  3. 生成操盘日志 (DeepSeek 大模型版 / 免费规则版)
  4. 微信推送 (Server酱)  —— 账户概览 + 今日成交 + 操盘日志 + 持仓
  5. 账户状态写回 state/paper_account.json (由 CI 提交回仓库, 实现持久化)

本地手动测试 (不推送):
    python run_ai_trader.py --dry-run

凭证均从环境变量读取, 不写死:
    SCT_KEY          Server酱 SendKey (微信推送)
    LLM_API_KEY      大模型 API Key (可选, DeepSeek 等; 缺省用免费规则版)
    LLM_PROVIDER     大模型厂商, 如 deepseek (可选)

全部为历史/模拟演示, 不构成投资建议。
"""
from __future__ import annotations

import os
import sys
import datetime as dt

import engine
import paper
import llm
import notify

# Windows 控制台默认 gbk 编码打不出 emoji, 统一切 UTF-8 (对 CI/Linux 无副作用)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 账户状态持久化到 state/ 目录, 由 CI 提交回仓库 (云端文件系统是临时的, 必须落库)
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
STATE_PATH = os.path.join(STATE_DIR, "paper_account.json")   # 兼容旧引用 (美股账户)

# 两个市场各一个独立模拟账户
MARKETS = [
    {"key": "us", "label": "🇺🇸 美股科技池", "watchlist": engine.DEFAULT_WATCHLIST,
     "benchmark": engine.BENCHMARK, "bench_label": "QQQ", "cur": "$",
     "state": os.path.join(STATE_DIR, "paper_account.json")},
    {"key": "cn", "label": "🇨🇳 A股龙头池", "watchlist": engine.A_SHARE_WATCHLIST,
     "benchmark": engine.A_BENCHMARK, "bench_label": "沪深300", "cur": "¥",
     "state": os.path.join(STATE_DIR, "paper_account_cn.json")},
]


# ---------------------------------------------------------------- 微信报告 (单市场分段)
def build_market_section(label: str, res: dict, summ: dict,
                         trades: list[dict], journal: str, regime: str,
                         cur: str = "$") -> str:
    lines = []
    lines.append(f"## {label}")
    if regime:
        lines.append(f"大盘环境: **{regime}**")
    lines.append("")

    # 账户概览
    lines.append("### 💼 账户概览")
    lines.append(
        f"- 总资产: **{cur}{summ['total']:,.0f}**  "
        f"(累计 {summ['ret_pct']:+.1f}%)\n"
        f"- 现金: {cur}{summ['cash']:,.0f}　持仓市值: {cur}{summ['invested']:,.0f}\n"
        f"- 持仓 {summ['n_pos']} 只　累计成交 {summ['n_trades']} 笔")
    lines.append("")

    # 今日成交
    lines.append("### 🔁 今日调仓")
    if trades:
        lines.append("| 方向 | 代码 | 名称 | 金额 | 理由 |")
        lines.append("|---|---|---|---|---|")
        for t in trades:
            side = "🟢买" if t["side"] == "BUY" else "🔴卖"
            pnl = f"，盈亏{cur}{t['pnl']:,.0f}" if t.get("pnl") else ""
            lines.append(
                f"| {side} | **{t['code']}** | {t.get('name','')} | "
                f"{cur}{t['amount']:,.0f} | {t['reason']}{pnl} |")
    else:
        lines.append("今日信号未触发调仓，维持原持仓观望。")
    lines.append("")

    # 操盘日志
    lines.append("### 📓 操盘日志")
    lines.append(journal)
    lines.append("")

    # 当前持仓
    rows = summ.get("rows", [])
    if rows:
        lines.append("### 📊 当前持仓")
        lines.append("| 代码 | 名称 | 市值 | 盈亏% |")
        lines.append("|---|---|---|---|")
        for r in rows[:12]:
            emo = "🟢" if r["盈亏%"] > 0 else ("🔴" if r["盈亏%"] < 0 else "⚪")
            lines.append(
                f"| **{r['代码']}** | {r['名称']} | {cur}{r['市值']:,.0f} | "
                f"{emo}{r['盈亏%']:+.1f}% |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------- 单市场跑一遍
def run_one_market(m: dict, dry: bool) -> dict | None:
    """分析→调仓→日志, 保存账户, 返回 {section, summ, title_bit} 或 None(无数据)。"""
    label, cur = m["label"], m["cur"]
    print(f"\n--- {label} ---")
    print(f"股票池: {', '.join(m['watchlist'])}")
    res = engine.analyze(m["watchlist"], period="2y", use_news=False,
                         use_earnings=False, benchmark=m["benchmark"],
                         bench_label=m["bench_label"])
    detail = res.get("detail", {})
    if not detail:
        print(f"❌ {label} 无可用行情数据, 跳过。")
        return None
    print(f"已分析 {len(detail)} 只标的, asof={res.get('asof')}")
    regime = (res.get("regime", {}) or {}).get("label", "")

    os.makedirs(STATE_DIR, exist_ok=True)
    acc = paper.load_account(m["state"])
    trades = paper.rebalance(acc, detail, names=m["watchlist"], reason_regime=regime)
    summ = paper.summary(acc, detail)
    print(f"今日成交 {len(trades)} 笔; 总资产 {cur}{summ['total']:,.0f} ({summ['ret_pct']:+.1f}%)")

    if not dry:
        paper.save_account(acc, m["state"])
        print(f"账户已保存: {m['state']}")

    # 操盘日志: 有大模型 key 用大模型版, 否则免费规则版
    fb = "、".join(f"{r['代码']}{r['盈亏%']:+.0f}%" for r in summ["rows"][:5])
    creds = llm.get_credentials()
    if creds.get("api_key"):
        journal = llm.llm_journal(trades, summ, regime=regime, factors_brief=fb, creds=creds, cur=cur)
    else:
        journal = llm.rule_based_journal(trades, summ, regime=regime, cur=cur)

    section = build_market_section(label, res, summ, trades, journal, regime, cur=cur)
    title_bit = f"{m['key'].upper()} {cur}{summ['total']:,.0f}({summ['ret_pct']:+.1f}%)"
    return {"section": section, "summ": summ, "title_bit": title_bit, "asof": res["asof"]}


# ---------------------------------------------------------------- 主流程
def main() -> int:
    dry = "--dry-run" in sys.argv
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] AI 交易员 每日运行开始… (dry_run={dry})")

    results = []
    for m in MARKETS:
        try:
            r = run_one_market(m, dry)
            if r:
                results.append(r)
        except Exception as e:
            print(f"⚠️ {m['label']} 运行异常: {e}")

    if not results:
        print("❌ 两个市场均无可用数据, 退出。")
        return 1

    asof = results[0]["asof"]
    md = ("\n\n---\n\n").join(r["section"] for r in results)
    md += "\n\n> ⚠️ 全部为模拟演示，仅供研究，非投资建议。"
    title = "🤖 AI交易员 " + asof[:10] + "  " + " / ".join(r["title_bit"] for r in results)

    if dry:
        print("\n===== 微信推送内容预览 (dry-run, 未发送) =====\n")
        print(title)
        print(md)
    else:
        r = notify.send_wechat(title, md)
        print(r)

    print(f"[{stamp}] 完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
