"""策略解读生成 (explain.py)
==========================
把 engine.analyze() 得到的单只标的 detail 字典, 翻译成"人话"策略解读:
  - 一句话结论 + 操作建议
  - 为什么给这个信号 (最强/最弱因子归因)
  - 技术位置 (均线/RSI/趋势强度)
  - 风控 (止损/目标/盈亏比)
  - 需要注意的风险点 (财报/波动/数据不足)

不做任何投资建议, 只是把已算出的量化结果用自然语言解释清楚。
"""
from __future__ import annotations

import pandas as pd

# 因子 -> (含义, 高分正面话术, 低分负面话术)
_FACTOR_MEAN = {
    "基本面": ("营收/盈利/估值等基本面", "基本面稳健", "基本面偏弱"),
    "趋势": ("均线与技术趋势", "趋势向上", "趋势走弱"),
    "分析师": ("华尔街评级与目标价", "机构看法偏乐观", "机构态度谨慎"),
    "动量": ("近期价格动量", "上涨动量强", "动量不足"),
    "盈利质量": ("盈利质量与财报超预期", "盈利质量高", "盈利质量一般"),
    "资金流": ("主力资金流向(OBV/CMF)", "资金持续流入", "资金流出"),
    "筹码面": ("机构持股/做空等筹码结构", "筹码结构健康", "筹码结构偏空"),
    "风险": ("波动与回撤风险", "波动可控", "波动偏大"),
    "相对大盘": ("相对基准的强弱", "跑赢大盘", "跑输大盘"),
    "板块热度": ("所处行业板块的热度", "身处热点板块", "板块偏冷"),
    "新闻情绪": ("近期新闻情绪", "新闻面偏正面", "新闻面偏负面"),
    "强弱": ("综合多空强弱", "整体偏强", "整体偏弱"),
}


def _action_line(score: float, action: str) -> str:
    if score >= 70:
        return (f"综合分 **{score}**，信号「**{action}**」——多个因子共振明显偏多，"
                "属于当前性价比较高的标的，可考虑分批建仓。")
    if score >= 58:
        return (f"综合分 **{score}**，信号「**{action}**」——整体偏多，"
                "可考虑逢回调分批介入，注意控制单票仓位。")
    if score >= 45:
        return (f"综合分 **{score}**，信号「**{action}**」——多空较均衡，"
                "建议观望或维持现有仓位，等更明确的方向。")
    if score >= 35:
        return (f"综合分 **{score}**，信号「**{action}**」——偏空，"
                "已持仓可考虑逢反弹减仓、收紧止损。")
    return (f"综合分 **{score}**，信号「**{action}**」——明显偏空，"
            "多数因子走弱，倾向回避或离场观望。")


def _attribution(factors: dict) -> tuple[list[str], list[str]]:
    """返回 (利多归因, 利空归因) 两组话术。"""
    pos, neg = [], []
    for name, val in factors.items():
        m = _FACTOR_MEAN.get(name)
        if not m or val is None:
            continue
        try:
            v = float(val)
        except Exception:
            continue
        mean, good, bad = m
        if v >= 65:
            pos.append(f"**{name}** {good}（{v:.0f}分，{mean}）")
        elif v <= 38:
            neg.append(f"**{name}** {bad}（{v:.0f}分，{mean}）")
    # 分数高的排前面
    return pos[:4], neg[:4]


def _tech_line(last: pd.Series) -> list[str]:
    out = []
    close = last.get("Close")
    s20, s50, s200 = last.get("SMA20"), last.get("SMA50"), last.get("SMA200")

    def ok(x):
        return x is not None and pd.notna(x)

    # 均线排列
    if all(ok(x) for x in (close, s20, s50, s200)):
        if close > s20 > s50 > s200:
            out.append("价格站上 20/50/200 日均线且多头排列，中长期趋势偏多。")
        elif close < s20 < s50 < s200:
            out.append("价格跌破 20/50/200 日均线且空头排列，中长期趋势偏空。")
        elif close > s200:
            out.append("价格在 200 日均线上方，中长期仍偏多，短期均线有缠绕。")
        else:
            out.append("价格在 200 日均线下方，中长期仍承压。")

    # RSI
    rsi = last.get("RSI")
    if ok(rsi):
        if rsi >= 70:
            out.append(f"RSI {rsi:.0f} 进入超买区，短期有回调/震荡风险，追高需谨慎。")
        elif rsi <= 30:
            out.append(f"RSI {rsi:.0f} 进入超卖区，短期可能出现技术性反弹。")
        else:
            out.append(f"RSI {rsi:.0f} 处于中性区间，未见明显超买超卖。")

    # ADX 趋势强度
    adx = last.get("ADX")
    if ok(adx):
        if adx >= 25:
            out.append(f"ADX {adx:.0f}（>25）说明当前趋势力度较强，顺势操作胜率更高。")
        else:
            out.append(f"ADX {adx:.0f}（<25）趋势偏弱，更像震荡行情，适合高抛低吸。")
    return out


def _risk_line(plan: dict, cur: str) -> str:
    try:
        up = float(plan.get("目标%", 0))
        dn = abs(float(plan.get("止损%", 0)))
        rr = (up / dn) if dn > 0 else 0
    except Exception:
        rr = 0
    line = (f"风控参考：现价 {cur}{plan.get('现价')}，"
            f"止损 {cur}{plan.get('止损价')}（{plan.get('止损%')}%），"
            f"目标 {cur}{plan.get('目标价')}（+{plan.get('目标%')}%）。")
    if rr:
        judge = "盈亏比不错，值得参与" if rr >= 1.8 else ("盈亏比一般，仓位别重" if rr >= 1 else "盈亏比偏低，性价比不高")
        line += f" 盈亏比约 **{rr:.1f} : 1**（{judge}）。止损目标基于 ATR 波动自动计算。"
    return line


def build_explanation(info: dict, cur: str = "$", reg: dict | None = None) -> dict:
    """返回 {结论, 利多, 利空, 技术, 风控, 提示} 的解读文本。"""
    factors = info.get("factors", {}) or {}
    plan = info.get("plan", {}) or {}
    score = info.get("score", 0)
    action = info.get("action", "")

    pos, neg = _attribution(factors)
    try:
        last = info["df"].iloc[-1]
        tech = _tech_line(last)
    except Exception:
        tech = []

    notes = []
    # 大盘环境
    if reg and reg.get("label"):
        notes.append(f"大盘环境：{reg['label']}（择时分 {reg.get('score','-')}）。"
                     "Risk-On 时系统整体略加分，Risk-Off 时略减分。")
    # 财报
    earn = info.get("earnings")
    if earn and earn.get("soon"):
        notes.append(f"⚠️ {earn['days']} 天后（{earn['date']}）发财报，财报前后波动大，"
                     "可等财报落地再决策。")
    # 波动
    try:
        vol = float(last.get("vol_ann"))
        if vol >= 0.6:
            notes.append(f"年化波动约 {vol:.0%}，属于高波动品种，建议降低仓位、严格止损。")
    except Exception:
        pass
    # 数据不足
    if info.get("insufficient"):
        notes.append(f"上市仅 {info.get('n_bars','?')} 个交易日，技术指标样本不足，"
                     "综合分主要参考短期价格与新闻，仅供观察。")

    return {
        "结论": _action_line(score, action),
        "利多": pos,
        "利空": neg,
        "技术": tech,
        "风控": _risk_line(plan, cur),
        "提示": notes,
    }
