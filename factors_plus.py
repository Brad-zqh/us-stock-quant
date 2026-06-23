"""
进阶因子模块 (factors_plus.py)
=============================
在技术 + 新闻之外, 再加三个机构级因子, 每个 0~100 (越高越看多):

  1. 基本面 fundamental : PEG / 营收增速 / 毛利率 / ROE / 净利率
  2. 分析师 analyst      : 华尔街评级均值 / 目标价上行空间 / 覆盖度
  3. 资金流 moneyflow    : OBV 斜率 / Chaikin 资金流(CMF) / 放量 / 52周高点突破

基本面与分析师数据来自 yfinance .info (按 ticker 缓存)。
"""
from __future__ import annotations
import numpy as np

_INFO_CACHE: dict[str, dict] = {}


def get_info(ticker: str) -> dict:
    if ticker not in _INFO_CACHE:
        import yfinance as yf
        try:
            _INFO_CACHE[ticker] = yf.Ticker(ticker).info or {}
        except Exception:
            _INFO_CACHE[ticker] = {}
    return _INFO_CACHE[ticker]


def _clip(x, lo=0, hi=100):
    return float(np.clip(x, lo, hi))


# ---------------------------------------------------------------- 基本面
def fundamental_factor(info: dict) -> tuple[float, dict]:
    s, detail = 50.0, {}
    peg = info.get("pegRatio") or info.get("trailingPegRatio")
    if peg and peg > 0:
        # PEG <1 便宜, >2.5 偏贵
        s += _clip(40 * (1.2 - peg), -25, 22)
        detail["PEG"] = round(peg, 2)
    rg = info.get("revenueGrowth")
    if rg is not None:
        s += np.clip(rg * 60, -15, 20)            # 营收增速
        detail["营收增速%"] = round(rg * 100, 1)
    gm = info.get("grossMargins")
    if gm is not None:
        s += np.clip((gm - 0.4) * 40, -8, 12)     # 毛利率
        detail["毛利率%"] = round(gm * 100, 1)
    roe = info.get("returnOnEquity")
    if roe is not None:
        s += np.clip(roe * 30, -8, 14)            # ROE
        detail["ROE%"] = round(roe * 100, 1)
    pm = info.get("profitMargins")
    if pm is not None:
        s += np.clip(pm * 30, -8, 10)             # 净利率
        detail["净利率%"] = round(pm * 100, 1)
    return _clip(s), detail


# ---------------------------------------------------------------- 分析师
def analyst_factor(info: dict, price: float | None = None) -> tuple[float, dict]:
    s, detail = 50.0, {}
    rec = info.get("recommendationMean")          # 1=强买 ... 5=强卖
    if rec:
        s += (3 - rec) * 22                        # 越接近1越高分
        detail["评级均值"] = round(rec, 2)
        detail["评级"] = info.get("recommendationKey", "")
    tgt = info.get("targetMeanPrice")
    px = price or info.get("currentPrice")
    if tgt and px:
        upside = tgt / px - 1
        s += np.clip(upside * 90, -25, 28)         # 目标价上行空间
        detail["目标价"] = round(tgt, 1)
        detail["上行%"] = round(upside * 100, 1)
    n = info.get("numberOfAnalystOpinions")
    if n:
        s += np.clip((n - 5) * 0.4, -4, 6)         # 覆盖度 (越多越可信)
        detail["分析师数"] = int(n)
    return _clip(s), detail


# ---------------------------------------------------------------- 资金流
def moneyflow_factor(d) -> tuple[float, dict]:
    s, detail = 50.0, {}
    last = d.iloc[-1]
    # OBV 斜率 (近 20 日)
    if "OBV" in d and len(d) > 21:
        obv = d["OBV"].tail(20)
        slope = np.polyfit(range(len(obv)), obv.values, 1)[0]
        norm = slope / (abs(d["OBV"]).tail(60).mean() + 1e-9)
        s += np.clip(norm * 400, -18, 18)
        detail["OBV趋势"] = "上升" if slope > 0 else "下降"
    cmf = last.get("CMF")
    if cmf is not None and np.isfinite(cmf):
        s += np.clip(cmf * 120, -20, 20)           # CMF > 0 资金流入
        detail["CMF"] = round(float(cmf), 3)
    mfi = last.get("MFI")
    if mfi is not None and np.isfinite(mfi):
        # MFI: 量价版RSI, >80超买减分, <20超卖加分, 中枢偏多
        s += np.clip((mfi - 50) * 0.25, -10, 10)
        if mfi > 80:
            s -= 8
        elif mfi < 20:
            s += 8
        detail["MFI"] = round(float(mfi), 1)
    vr = last.get("vol_ratio")
    c, hi = last["Close"], last.get("hi_52w")
    if vr is not None and np.isfinite(vr) and hi and c >= hi * 0.99:
        s += np.clip((vr - 1) * 14, 0, 14)         # 放量突破 52 周高
        detail["突破"] = "52周新高放量" if vr > 1.3 else "近52周高"
    elif hi and np.isfinite(c):
        detail["距52周高%"] = round((c / hi - 1) * 100, 1)
    return _clip(s), detail


# ---------------------------------------------------------------- 筹码面 (主力/空头持仓)
def positioning_factor(info: dict) -> tuple[float, dict]:
    s, detail = 50.0, {}
    inst = info.get("heldPercentInstitutions")
    if inst is not None:
        # 机构持股 40%~85% 较健康; 过低=缺乏认可, 过高=拥挤
        s += np.clip((inst - 0.45) * 50, -12, 16)
        detail["机构持股%"] = round(inst * 100, 1)
    ins = info.get("heldPercentInsiders")
    if ins is not None:
        s += np.clip(ins * 40, 0, 10)            # 内部人持股=利益绑定
        detail["内部人%"] = round(ins * 100, 1)
    spf = info.get("shortPercentOfFloat")
    if spf is not None:
        # 做空比例高=空头看空(利空); >15% 标挤压风险
        s -= np.clip(spf * 120, 0, 22)
        detail["做空比例%"] = round(spf * 100, 1)
        if spf > 0.15:
            detail["提示"] = "高做空, 留意逼空"
    sr = info.get("shortRatio")
    if sr is not None:
        detail["回补天数"] = round(sr, 1)
    return _clip(s), detail


# ---------------------------------------------------------------- 盈利质量 (惊喜/增速)
def _earnings_surprises(ticker: str) -> list:
    key = "_surp_" + ticker
    if key in _INFO_CACHE:
        return _INFO_CACHE[key]
    vals = []
    try:
        import yfinance as yf
        ed = yf.Ticker(ticker).get_earnings_dates(limit=8)
        if ed is not None and "Surprise(%)" in ed:
            vals = [float(x) for x in ed["Surprise(%)"].dropna().head(4)]
    except Exception:
        vals = []
    _INFO_CACHE[key] = vals
    return vals


def earnings_quality_factor(ticker: str, info: dict) -> tuple[float, dict]:
    s, detail = 50.0, {}
    surp = _earnings_surprises(ticker)
    if surp:
        avg = float(np.mean(surp))
        beats = sum(1 for x in surp if x > 0)
        s += np.clip(avg * 2.5, -18, 18)          # 平均惊喜
        s += (beats - len(surp) / 2) * 4          # 超预期次数
        detail["近4季均惊喜%"] = round(avg, 1)
        detail["超预期"] = f"{beats}/{len(surp)}次"
    eg = info.get("earningsQuarterlyGrowth")
    if eg is not None:
        s += np.clip(eg * 25, -15, 18)            # 盈利同比增速
        detail["盈利增速%"] = round(eg * 100, 1)
    fe, te = info.get("forwardEps"), info.get("trailingEps")
    if fe and te and te != 0:
        chg = fe / te - 1
        s += np.clip(chg * 40, -12, 15)           # 预期EPS改善
        detail["EPS预期变化%"] = round(chg * 100, 1)
    return _clip(s), detail


def all_plus_factors(ticker: str, d) -> tuple[dict, dict]:
    """返回 ({因子名:分数}, {因子名:明细dict})。"""
    info = get_info(ticker)
    px = float(d["Close"].iloc[-1])
    f_fun, d_fun = fundamental_factor(info)
    f_ana, d_ana = analyst_factor(info, px)
    f_mf, d_mf = moneyflow_factor(d)
    f_pos, d_pos = positioning_factor(info)
    f_eq, d_eq = earnings_quality_factor(ticker, info)
    scores = {"基本面": round(f_fun, 1), "分析师": round(f_ana, 1),
              "资金流": round(f_mf, 1), "筹码面": round(f_pos, 1),
              "盈利质量": round(f_eq, 1)}
    details = {"基本面": d_fun, "分析师": d_ana, "资金流": d_mf,
               "筹码面": d_pos, "盈利质量": d_eq}
    return scores, details


if __name__ == "__main__":
    import engine
    for tk in ["NVDA", "AAPL", "MU"]:
        d = engine.add_indicators(engine.fetch(tk, "1y")[tk])
        sc, dt = all_plus_factors(tk, d)
        print(tk, sc)
        print("   ", dt)
