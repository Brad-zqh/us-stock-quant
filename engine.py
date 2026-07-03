"""
量化选股引擎 (engine.py)
========================
多因子综合打分 + 择时信号 + ATR 风控 + 简易回测。

数据源: yfinance (日线)。所有指标纯 pandas/numpy 实现, 无需额外 TA 库。

核心产出 (对每只股票):
  - score      : 0~100 综合分
  - action     : 强烈买入 / 买入 / 持有 / 减仓 / 卖出
  - 各因子分项 : 趋势 / 动量 / 强弱 / 相对大盘 / 风险
  - 风控       : ATR 止损价、目标价、建议仓位%
  - 回测       : 策略净值 vs 买入持有
"""

from __future__ import annotations
import datetime as dt
import os
import numpy as np
import pandas as pd
import yfinance as yf

import quotes            # 行情数据层: 优先富途, 回退 yfinance

try:
    import news as news_mod          # 美股英文新闻情绪 (可选)
    _HAS_NEWS = True
except Exception:
    _HAS_NEWS = False

try:
    import cn_news                    # A股中文新闻情绪 (可选, 需 akshare)
    _HAS_CN_NEWS = True
except Exception:
    _HAS_CN_NEWS = False


def _news_provider(ticker: str):
    """按代码后缀选新闻源: .SS/.SZ -> 中文; 其余 -> 英文。"""
    if ticker.endswith((".SS", ".SZ")) and _HAS_CN_NEWS:
        return cn_news
    if _HAS_NEWS:
        return news_mod
    return None


try:
    import futu_news                     # 富途多市场新闻源 (免OpenD/免key, 云端可用)
    _HAS_FUTU_NEWS = True
except Exception:
    _HAS_FUTU_NEWS = False


def _fetch_sentiment(t: str, name: str, use_news: bool) -> tuple[float, list]:
    """新闻情绪: 优先富途多市场新闻源, 空则回退 yfinance/akshare。"""
    if not use_news:
        return 50.0, []
    if _HAS_FUTU_NEWS and futu_news.enabled():
        try:
            f, items = futu_news.sentiment_factor(t, name)
            if items:
                return f, items
        except Exception:
            pass
    prov = _news_provider(t)
    if prov is not None:
        try:
            return prov.sentiment_factor(t)
        except Exception:
            return 50.0, []
    return 50.0, []

try:
    import factors_plus              # 基本面/分析师/资金流 (可选)
    _HAS_PLUS = True
except Exception:
    _HAS_PLUS = False

try:
    import sector_factor             # 板块热度 (板块热点) 因子 (可选, SECTOR_FACTOR=0 关闭)
    _HAS_SECTOR = True
except Exception:
    _HAS_SECTOR = False

# ----------------------------------------------------------------------------
# 你的自选股 (可在 app 里改). 名称仅作显示用.
# ----------------------------------------------------------------------------
DEFAULT_WATCHLIST = {
    # 💾 存储 / 内存 (高弹性)
    "SNDK": "闪迪 SanDisk",
    "MU":   "美光科技 Micron",
    "STX":  "希捷 Seagate",
    "WDC":  "西部数据 WDC",
    # 🔬 半导体 / 算力
    "NVDA": "英伟达 Nvidia",
    "AMD":  "超威 AMD",
    "AVGO": "博通 Broadcom",
    "MRVL": "迈威尔 Marvell",
    "SMCI": "超微 Supermicro",
    # ⚙️ 半导体设备
    "AMAT": "应用材料 AMAT",
    "LRCX": "泛林 Lam Research",
    "KLAC": "科磊 KLA",
    # 🔦 光通信 / 网络
    "LITE": "Lumentum",
    "ANET": "Arista 网络",
    # 🚀 高波成长
    "PLTR": "Palantir",
    "CRWD": "CrowdStrike",
    "NET":  "Cloudflare",
    "SNOW": "Snowflake",
    # 🏛️ 科技大盘 (压舱)
    "AAPL": "苹果 Apple",
    "TSLA": "特斯拉 Tesla",
    "MSFT": "微软 Microsoft",
}
BENCHMARK = "QQQ"   # 相对强度基准 (纳指 ETF, 科技股更合适)

# A股龙头池 (yfinance 后缀: .SS 上证 / .SZ 深证), AI 交易员 A股账户默认池
A_SHARE_WATCHLIST = {
    "600519.SS": "贵州茅台",
    "300750.SZ": "宁德时代",
    "601318.SS": "中国平安",
    "000858.SZ": "五粮液",
    "600036.SS": "招商银行",
    "002594.SZ": "比亚迪",
    "000333.SZ": "美的集团",
    "600900.SS": "长江电力",
}
A_BENCHMARK = "510300.SS"   # 沪深300 ETF, A股大盘择时基准


# ----------------------------------------------------------------------------
# 数据获取
# ----------------------------------------------------------------------------
def fetch(tickers, period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
    """返回 {ticker: OHLCV DataFrame}. 自动复权。
    数据源: 优先富途 OpenD (本地), 失败/云端回退 yfinance —— 见 quotes.py。"""
    return quotes.fetch(tickers, period=period, interval=interval)


# ----------------------------------------------------------------------------
# 技术指标 (纯 pandas)
# ----------------------------------------------------------------------------
def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = -delta.clip(upper=0).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["Close"]
    d["SMA20"] = c.rolling(20).mean()
    d["SMA50"] = c.rolling(50).mean()
    d["SMA200"] = c.rolling(200).mean()
    d["EMA12"] = _ema(c, 12)
    d["EMA26"] = _ema(c, 26)
    d["MACD"] = d["EMA12"] - d["EMA26"]
    d["MACD_signal"] = _ema(d["MACD"], 9)
    d["MACD_hist"] = d["MACD"] - d["MACD_signal"]
    d["RSI"] = _rsi(c, 14)
    mb = c.rolling(20).mean()
    sd = c.rolling(20).std()
    d["BB_up"] = mb + 2 * sd
    d["BB_dn"] = mb - 2 * sd
    d["BB_pctB"] = (c - d["BB_dn"]) / (d["BB_up"] - d["BB_dn"])
    d["ATR"] = _atr(d, 14)
    # ADX 趋势强度 (>25 趋势强, <20 震荡)
    h, l = d["High"], d["Low"]
    up_move = h.diff()
    dn_move = -l.diff()
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=d.index).ewm(alpha=1/14, adjust=False).mean() / atr14
    minus_di = 100 * pd.Series(minus_dm, index=d.index).ewm(alpha=1/14, adjust=False).mean() / atr14
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    d["ADX"] = dx.ewm(alpha=1/14, adjust=False).mean()
    d["plus_DI"], d["minus_DI"] = plus_di, minus_di
    # KDJ 随机指标
    low_n = l.rolling(9).min()
    high_n = h.rolling(9).max()
    rsv = (c - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    d["K"] = rsv.ewm(com=2, adjust=False).mean()
    d["D"] = d["K"].ewm(com=2, adjust=False).mean()
    d["J"] = 3 * d["K"] - 2 * d["D"]
    # MFI 资金流量指标 (量价版 RSI)
    tp = (h + l + c) / 3
    mf = tp * d["Volume"]
    pos_mf = mf.where(tp > tp.shift(), 0).rolling(14).sum()
    neg_mf = mf.where(tp < tp.shift(), 0).rolling(14).sum()
    d["MFI"] = 100 - 100 / (1 + pos_mf / neg_mf.replace(0, np.nan))
    # 资金流指标
    vol = d["Volume"].replace(0, np.nan)
    d["OBV"] = (np.sign(c.diff()).fillna(0) * d["Volume"]).cumsum()
    mfm = ((c - d["Low"]) - (d["High"] - c)) / (d["High"] - d["Low"]).replace(0, np.nan)
    mfv = mfm.fillna(0) * d["Volume"]
    d["CMF"] = mfv.rolling(20).sum() / vol.rolling(20).sum()    # Chaikin Money Flow
    d["vol_ratio"] = d["Volume"] / d["Volume"].rolling(20).mean()  # 放量倍数
    d["hi_52w"] = c.rolling(min(252, len(d))).max()
    d["ret"] = c.pct_change()
    d["vol_ann"] = d["ret"].rolling(20).std() * np.sqrt(252)
    d["mom_126"] = c.pct_change(126)   # ~6 个月动量
    d["mom_21"] = c.pct_change(21)     # ~1 个月动量
    return d


# ----------------------------------------------------------------------------
# 多因子打分: 每个分项 0~100, 越高越看多
# ----------------------------------------------------------------------------
def _clip01(x: float) -> float:
    return float(np.clip(x, 0, 100))


def score_factors(d: pd.DataFrame, bench: pd.Series | None = None) -> dict:
    last = d.iloc[-1]
    c = last["Close"]

    # 1) 趋势: 价格相对 SMA50/200 + 多头排列 + 金叉
    trend = 50.0
    if not np.isnan(last["SMA50"]):
        trend += 15 if c > last["SMA50"] else -15
    if not np.isnan(last["SMA200"]):
        trend += 20 if c > last["SMA200"] else -20
    if not np.isnan(last["SMA50"]) and not np.isnan(last["SMA200"]):
        trend += 15 if last["SMA50"] > last["SMA200"] else -15   # 金叉/死叉
    # ADX 趋势强度加权: 强趋势放大方向, 震荡市削弱
    adx, pdi, mdi = last.get("ADX"), last.get("plus_DI"), last.get("minus_DI")
    if adx is not None and np.isfinite(adx):
        direction = 1 if (pdi or 0) >= (mdi or 0) else -1
        if adx > 25:
            trend += direction * min((adx - 25) * 0.6, 15)        # 强趋势确认
        elif adx < 20:
            trend = 50 + (trend - 50) * 0.6                        # 震荡市打折
    trend = _clip01(trend)

    # 2) 动量: MACD 柱 + 6 月/1 月动量
    mom = 50.0
    if last["MACD_hist"] > 0:
        mom += 12
    else:
        mom -= 12
    if not np.isnan(last["mom_126"]):
        mom += _clip01(last["mom_126"] * 100) - 50  # 映射
        mom += np.clip(last["mom_126"] * 80, -20, 20)
    if not np.isnan(last["mom_21"]):
        mom += np.clip(last["mom_21"] * 120, -18, 18)
    # KDJ: 金叉(K上穿D)加分, 高位钝化减分
    k, dval, j = last.get("K"), last.get("D"), last.get("J")
    if k is not None and np.isfinite(k):
        mom += 8 if k > dval else -8
        if j is not None and np.isfinite(j):
            if j > 100:
                mom -= 6          # 超买钝化
            elif j < 0:
                mom += 6          # 超卖
    mom = _clip01(mom)

    # 3) 强弱 (均值回归过滤): RSI + 布林 %B
    #    过热(>70) 扣分, 超卖(<30) 在趋势向上时反而是机会
    strength = 50.0
    rsi = last["RSI"]
    if rsi > 75:
        strength -= 25
    elif rsi > 65:
        strength -= 10
    elif rsi < 30:
        strength += 18   # 超卖反弹机会
    elif rsi < 40:
        strength += 8
    pctb = last["BB_pctB"]
    if not np.isnan(pctb):
        if pctb > 1.0:
            strength -= 15   # 冲出布林上轨, 短期过热
        elif pctb < 0.0:
            strength += 12   # 跌破下轨, 短期超卖
    strength = _clip01(strength)

    # 4) 相对大盘强度 (vs QQQ, 过去 63 日)
    rs = 50.0
    if bench is not None and len(bench) > 64:
        stock_ret = d["Close"].pct_change(63).iloc[-1]
        bench_ret = bench.pct_change(63).iloc[-1]
        if not np.isnan(stock_ret) and not np.isnan(bench_ret):
            rs = _clip01(50 + (stock_ret - bench_ret) * 150)

    # 5) 风险 (波动率越低分越高, 高分 = 更可控)
    risk = 50.0
    v = last["vol_ann"]
    if not np.isnan(v):
        # 年化波动 20% -> 60 分, 80% -> 低分
        risk = _clip01(90 - v * 100)

    return {
        "趋势": round(trend, 1),
        "动量": round(mom, 1),
        "强弱": round(strength, 1),
        "相对大盘": round(rs, 1),
        "风险": round(risk, 1),
    }


# 因子权重 (12 因子: 技术 + 情绪 + 基本面 + 分析师 + 资金流 + 筹码面 + 盈利质量 + 板块热度)
WEIGHTS = {"基本面": 0.14, "趋势": 0.13, "分析师": 0.11, "动量": 0.10,
           "盈利质量": 0.10, "资金流": 0.09, "筹码面": 0.08, "风险": 0.08,
           "相对大盘": 0.07, "板块热度": 0.06, "新闻情绪": 0.06, "强弱": 0.04}

# 若存在 calibrated_weights.json (由 calibrate.py 用历史 IC 校准生成), 自动加载覆盖。
# 删除该文件即可回退到上面的默认权重。保持温和、可解释, 不引入黑盒。
def _load_calibrated_weights():
    try:
        import json
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "calibrated_weights.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            w = data.get("weights") if isinstance(data, dict) else None
            if isinstance(w, dict) and w:
                # 只接受已知因子, 且做归一化, 防止脏数据
                clean = {k: float(v) for k, v in w.items() if k in WEIGHTS}
                tot = sum(clean.values())
                if clean and tot > 0:
                    WEIGHTS.update({k: round(v / tot, 4) for k, v in clean.items()})
    except Exception:
        pass


_load_calibrated_weights()

# 若关闭基本面/分析师/资金流, 用这套纯技术权重 (自动归一化)
def _effective_weights(factors: dict) -> dict:
    w = {k: v for k, v in WEIGHTS.items() if k in factors}
    tot = sum(w.values()) or 1
    return {k: v / tot for k, v in w.items()}


def composite(factors: dict) -> float:
    w = _effective_weights(factors)
    return round(sum(factors[k] * w[k] for k in w), 1)


def action_from_score(score: float) -> tuple[str, str]:
    """返回 (动作, 颜色). A股习惯: 红=看多/买, 绿=看空/卖."""
    if score >= 70:
        return "强烈买入 ▲▲", "#dc2626"   # 红
    if score >= 58:
        return "买入 ▲", "#ef4444"        # 红
    if score >= 45:
        return "持有 —", "#a3a3a3"        # 灰
    if score >= 35:
        return "减仓 ▼", "#f59e0b"        # 橙
    return "卖出 ▼▼", "#16a34a"          # 绿


# ----------------------------------------------------------------------------
# 风控建议: ATR 止损 / 目标 / 仓位
# ----------------------------------------------------------------------------
def risk_plan(d: pd.DataFrame, score: float) -> dict:
    last = d.iloc[-1]
    c = float(last["Close"])
    atr = float(last["ATR"])
    vol = float(last["vol_ann"])
    # ATR 缺失或异常 (次新股) 时退化为百分比止损
    if not np.isfinite(atr) or atr <= 0 or atr > 0.15 * c:
        stop = c * 0.92             # -8%
        target = c * 1.12           # +12%
    else:
        stop = c - 2.5 * atr        # 2.5×ATR 止损
        target = c + 4.0 * atr      # 4×ATR 目标 (盈亏比 ~1.6)
    # 仓位: 分数越高 + 波动越低, 仓位越大; 上限 25% 单票
    base = np.clip((score - 45) / 25, 0, 1)        # 45 分以下不建仓
    safe_vol = vol if np.isfinite(vol) and vol > 0 else 0.5
    vol_adj = np.clip(0.30 / max(safe_vol, 0.15), 0.3, 1.2)
    pos = float(np.clip(base * vol_adj * 0.25, 0, 0.25))
    if not np.isfinite(pos):
        pos = 0.0
    return {
        "现价": round(c, 2),
        "止损价": round(stop, 2),
        "目标价": round(target, 2),
        "止损%": round((stop / c - 1) * 100, 1),
        "目标%": round((target / c - 1) * 100, 1),
        "建议仓位%": round(pos * 100, 1),
    }


# ----------------------------------------------------------------------------
# 简易回测: 综合分 >= 58 满仓持有, < 45 空仓, 中间维持
# ----------------------------------------------------------------------------
def backtest(d: pd.DataFrame, bench: pd.Series | None = None) -> pd.DataFrame:
    """逐日重算综合分生成仓位, 对比买入持有. 返回净值 DataFrame."""
    df = d.copy()
    # 为速度: 用向量化近似的择时规则 (与打分逻辑同向)
    long_ok = (
        (df["Close"] > df["SMA50"])
        & (df["SMA50"] > df["SMA200"])
        & (df["MACD_hist"] > 0)
        & (df["RSI"] < 78)
    )
    exit_sig = (df["Close"] < df["SMA50"]) | (df["RSI"] > 80)
    pos = pd.Series(np.nan, index=df.index)
    pos[long_ok] = 1.0
    pos[exit_sig] = 0.0
    pos = pos.ffill().fillna(0.0).shift(1).fillna(0.0)   # 次日开盘执行
    strat_ret = pos * df["ret"]
    out = pd.DataFrame({
        "策略": (1 + strat_ret.fillna(0)).cumprod(),
        "买入持有": (1 + df["ret"].fillna(0)).cumprod(),
    })
    return out


def _perf_stats(equity: pd.Series, rets: pd.Series) -> dict:
    n = len(rets)
    if n < 2:
        return {}
    total = equity.iloc[-1] - 1
    cagr = equity.iloc[-1] ** (252 / n) - 1
    sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0
    dd = (equity / equity.cummax() - 1).min()
    active = rets[rets != 0]
    win = (active > 0).mean() * 100 if len(active) else 0
    return {
        "总收益%": round(total * 100, 1),
        "年化%": round(cagr * 100, 1),
        "夏普": round(sharpe, 2),
        "最大回撤%": round(dd * 100, 1),
        "持仓胜率%": round(win, 1),
    }


# ----------------------------------------------------------------------------
# 顶层: 一次性分析整个自选股
# ----------------------------------------------------------------------------
try:
    import earnings as earnings_mod   # 财报日提醒 (可选)
    _HAS_EARN = True
except Exception:
    _HAS_EARN = False


def _analyze_one(t, name, d, bench, use_news, use_fundamentals, use_earnings,
                 regime_mult=1.0):
    """单只股票的完整分析。设计为可并行调用 (网络请求是瓶颈)。"""
    n_bars = len(d)
    insufficient = n_bars < 60          # 不足以算 SMA50, 视为次新股
    factors = score_factors(d, bench)

    # 新闻情绪因子 (美股英文 / A股中文, 优先富途多市场新闻源, 回退 yfinance/akshare)
    sent, news_items = _fetch_sentiment(t, name, use_news)
    factors["新闻情绪"] = sent

    # 进阶因子: 基本面 / 分析师 / 资金流
    plus_detail = {}
    if use_fundamentals and _HAS_PLUS:
        try:
            plus_scores, plus_detail = factors_plus.all_plus_factors(t, d)
            factors.update(plus_scores)
        except Exception:
            pass

    # 板块热度因子 (板块热点: A股行业当日强弱 / 美股行业ETF动量; 取不到则中性50不计入)
    if _HAS_SECTOR and sector_factor.enabled():
        try:
            f_sec, sec_detail = sector_factor.sector_score(t, name, d,
                                                           heavy_ok=use_fundamentals)
            factors["板块热度"] = f_sec
            if sec_detail:
                plus_detail["板块热度"] = sec_detail
        except Exception:
            pass

    sc_raw = composite(factors)
    # 大盘环境微调: risk-on 略放大优势, risk-off 略压缩 (围绕50缩放偏离)
    sc = round(float(np.clip(50 + (sc_raw - 50) * regime_mult, 0, 100)), 1)
    action, color = action_from_score(sc)
    plan = risk_plan(d, sc)
    bt = backtest(d, bench)
    stats = _perf_stats(bt["策略"], bt["策略"].pct_change())
    bh = _perf_stats(bt["买入持有"], bt["买入持有"].pct_change())

    # 财报日临近 (仅自选股, 默认开; 大池子关闭以提速)
    earn = None
    if use_earnings and _HAS_EARN:
        try:
            earn = earnings_mod.next_earnings(t)
        except Exception:
            earn = None
    earn_cell = ""
    if earn:
        earn_cell = f"⚠️{earn['days']}天" if earn["soon"] else f"{earn['days']}天"

    disp_name = name + ("　⚠️数据不足" if insufficient else "")
    if insufficient:
        action = "观察 (次新股)"
    row = {"代码": t, "名称": disp_name, "综合分": sc,
           "信号": action, "_color": color, **factors, **plan,
           "距财报": earn_cell}
    det = {"df": d, "factors": factors, "score": sc, "action": action,
           "color": color, "plan": plan, "backtest": bt,
           "stats": stats, "bh_stats": bh, "news": news_items,
           "n_bars": n_bars, "insufficient": insufficient,
           "plus_detail": plus_detail, "earnings": earn}
    return t, row, det


# ----------------------------------------------------------------------------
# 组合模拟盘: 把整个自选股当成一个组合, 用策略信号逐日调仓, 看整体收益
# 直接复用每只股票已算好的 backtest (策略/买入持有净值), 无需重新拉数据
# ----------------------------------------------------------------------------
def portfolio_backtest(detail: dict, names: dict | None = None,
                       weight: str = "equal", capital: float = 100000.0) -> dict:
    """把 detail 里所有标的组合成一个模拟盘。

    weight: "equal" 每日等权再平衡 / "score" 按综合分静态加权
    capital: 初始资金, 用于换算最终金额

    返回 {strat_equity, bh_equity, strat_stats, bh_stats, contrib, capital,
          strat_final, bh_final} 。数据不足时 ok=False。
    """
    names = names or {}
    strat_cols, bh_cols, scores = {}, {}, {}
    for code, info in detail.items():
        bt = info.get("backtest")
        if bt is None or len(bt) < 5:
            continue
        sr = bt["策略"].pct_change()
        br = bt["买入持有"].pct_change()
        if sr.dropna().empty:
            continue
        strat_cols[code] = sr
        bh_cols[code] = br
        scores[code] = float(info.get("score", 50) or 50)

    if len(strat_cols) == 0:
        return {"ok": False}

    S = pd.DataFrame(strat_cols).sort_index()
    B = pd.DataFrame(bh_cols).sort_index()

    if weight == "score" and len(scores):
        w = pd.Series(scores, dtype=float)
        w = w.clip(lower=1)                 # 避免负/零权重
        w = w / w.sum()
        # 每日按当天有数据的列重新归一, 缺失当 0 收益 (空仓)
        def wmean(row):
            avail = row.dropna().index
            if len(avail) == 0:
                return 0.0
            ww = w.reindex(avail)
            ww = ww / ww.sum()
            return float((row.reindex(avail) * ww).sum())
        strat_ret = S.apply(wmean, axis=1)
        bh_ret = B.apply(wmean, axis=1)
        weights_disp = (w * 100).round(1)
    else:
        # 每日等权: 当天有数据的标的平均
        strat_ret = S.mean(axis=1, skipna=True).fillna(0.0)
        bh_ret = B.mean(axis=1, skipna=True).fillna(0.0)
        eqw = 100.0 / len(strat_cols)
        weights_disp = pd.Series({c: eqw for c in strat_cols}).round(1)

    strat_eq = (1 + strat_ret.fillna(0)).cumprod()
    bh_eq = (1 + bh_ret.fillna(0)).cumprod()

    # 每只标的贡献 (整段策略/买入持有总收益)
    contrib_rows = []
    for code in strat_cols:
        s_tot = (1 + S[code].fillna(0)).cumprod().iloc[-1] - 1
        b_tot = (1 + B[code].fillna(0)).cumprod().iloc[-1] - 1
        contrib_rows.append({
            "代码": code,
            "名称": names.get(code, ""),
            "综合分": round(scores.get(code, 50), 1),
            "权重%": float(weights_disp.get(code, 0)),
            "策略收益%": round(s_tot * 100, 1),
            "买入持有%": round(b_tot * 100, 1),
        })
    contrib = pd.DataFrame(contrib_rows).sort_values("策略收益%", ascending=False)

    return {
        "ok": True,
        "n": len(strat_cols),
        "strat_equity": strat_eq,
        "bh_equity": bh_eq,
        "strat_stats": _perf_stats(strat_eq, strat_ret),
        "bh_stats": _perf_stats(bh_eq, bh_ret),
        "contrib": contrib,
        "capital": capital,
        "strat_final": capital * float(strat_eq.iloc[-1]),
        "bh_final": capital * float(bh_eq.iloc[-1]),
    }


def market_regime(bench: pd.Series | None, label: str = "QQQ") -> dict:
    """大盘环境 (择时风险开关): 基准相对 200/50 日线 + 近一月动量。
    返回 {score 0~100, label, mult}. mult 用于轻微缩放个股分 (risk-on 略放大, risk-off 略压缩)。"""
    if bench is None or len(bench) < 60:
        return {"score": 50, "label": "未知", "mult": 1.0, "detail": ""}
    c = float(bench.iloc[-1])
    sma50 = bench.rolling(50).mean().iloc[-1]
    sma200 = bench.rolling(min(200, len(bench))).mean().iloc[-1]
    mom20 = c / bench.iloc[-21] - 1 if len(bench) > 21 else 0
    s = 50.0
    s += 18 if c > sma200 else -18
    s += 12 if c > sma50 else -12
    s += float(np.clip(mom20 * 200, -15, 15))
    s = float(np.clip(s, 0, 100))
    if s >= 65:
        rlabel, mult = "🟢 Risk-On 进攻", 1.05
    elif s >= 45:
        rlabel, mult = "🟡 中性", 1.0
    else:
        rlabel, mult = "🔴 Risk-Off 防御", 0.93
    detail = (f"{label} {'在' if c > sma200 else '跌破'}200日线, "
              f"{'在' if c > sma50 else '跌破'}50日线, 近月{mom20*100:+.1f}%")
    return {"score": round(s, 1), "label": rlabel, "mult": mult, "detail": detail}


def analyze(watchlist: dict[str, str], period: str = "2y",
            use_news: bool = True, use_fundamentals: bool = True,
            use_earnings: bool = False, max_workers: int = 8,
            use_regime: bool = True, benchmark: str = BENCHMARK,
            bench_label: str = "") -> dict:
    tickers = list(watchlist.keys())
    data = fetch(tickers + [benchmark], period=period)
    bench = data[benchmark]["Close"] if benchmark in data else None
    regime = market_regime(bench, label=bench_label or benchmark) if use_regime \
        else {"score": 50, "label": "—", "mult": 1.0, "detail": ""}

    # 预先算好(CPU)指标, 再并行做(网络)新闻/基本面/财报
    jobs = [(t, watchlist[t], add_indicators(data[t])) for t in tickers if t in data]

    results, detail = [], {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(jobs)))) as ex:
        futs = [ex.submit(_analyze_one, t, nm, d, bench,
                          use_news, use_fundamentals, use_earnings, regime["mult"])
                for t, nm, d in jobs]
        for f in futs:
            try:
                t, row, det = f.result()
                results.append(row)
                detail[t] = det
            except Exception:
                continue

    if results:
        table = pd.DataFrame(results).sort_values("综合分", ascending=False).reset_index(drop=True)
    else:
        table = pd.DataFrame()   # 全部行情拉取失败: 返回空表, 不崩
    return {"table": table, "detail": detail, "regime": regime,
            "asof": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}


if __name__ == "__main__":
    res = analyze(DEFAULT_WATCHLIST, period="2y")
    cols = ["代码", "名称", "综合分", "信号", "趋势", "动量", "强弱",
            "相对大盘", "风险", "现价", "止损价", "目标价", "建议仓位%"]
    print(res["table"][cols].to_string(index=False))
    print("\n更新时间:", res["asof"])
