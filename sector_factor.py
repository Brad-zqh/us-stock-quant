"""板块热度因子 (sector_factor.py)
==================================
把"板块热点"量化成一个 0~100 的因子 (越高=所处板块越热):

- A 股: 用东方财富**行业板块**当日强弱, 个股所属行业在全部行业里的涨幅分位。
        (板块热点通常就是看当下哪些行业在领涨)
- 美股: 用 11 个 SPDR 行业 ETF 的 3 个月动量, 个股所属 sector 的动量分位。

设计原则:
- 全程 try/except + 超时, 取不到数据就返回中性 50, 绝不拖垮主流程。
- 市场级排名数据 (美股 11 只 ETF / A 股行业表) 每进程缓存 ~30 分钟, 只拉一次,
  每只股票只做一次"查所属板块"的轻量映射。
- 环境变量 SECTOR_FACTOR=0 可整体关闭。
"""
from __future__ import annotations

import os
import time
import threading

_CACHE: dict = {}          # key -> (ts, value)
_TTL = 1800                # 市场级数据缓存 30 分钟


def enabled() -> bool:
    return os.getenv("SECTOR_FACTOR", "1") != "0"


def _cached(key: str, fn, ttl: int = _TTL):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


def _run_timeout(fn, timeout: float = 10.0):
    """在 daemon 子线程里跑 fn, 超时/异常返回 None。
    用 daemon 线程, 卡住的网络请求不会阻塞进程退出, 也不阻塞主流程。"""
    box = {}

    def _target():
        try:
            box["v"] = fn()
        except Exception:
            box["v"] = None

    th = threading.Thread(target=_target, daemon=True)
    th.start()
    th.join(timeout)
    return box.get("v")


def _rank_scores(pairs: list) -> dict:
    """pairs=[(name, momentum), ...] -> {name: 0~100 热度分} (分位映射到 35~95)。"""
    vals = [p for p in pairs if p[1] is not None]
    if not vals:
        return {}
    vals.sort(key=lambda x: x[1])
    n = len(vals)
    out = {}
    for i, (name, _) in enumerate(vals):
        pct = i / (n - 1) if n > 1 else 0.5
        out[name] = round(35 + 60 * pct, 1)
    return out


# ------------------------------------------------------------------ 美股
_US_ETF_BY_SECTOR = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financial": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def _us_sector_scores() -> dict:
    """返回 {sector名: 热度分}。用 11 只 SPDR 行业 ETF 的 63 日动量排名。"""
    def _work():
        import quotes
        etfs = sorted(set(_US_ETF_BY_SECTOR.values()))
        data = quotes.fetch(etfs, period="1y")
        mom = {}
        for tk, df in (data or {}).items():
            try:
                if df is None or len(df) < 64:
                    continue
                c = df["Close"]
                mom[tk] = float(c.iloc[-1] / c.iloc[-64] - 1.0)
            except Exception:
                continue
        if not mom:
            return {}
        etf_scores = _rank_scores(list(mom.items()))
        # 映射回 sector 名
        return {sec: etf_scores.get(etf)
                for sec, etf in _US_ETF_BY_SECTOR.items() if etf_scores.get(etf) is not None}

    res = _run_timeout(_work, timeout=15.0)
    return res or {}


def _us_ticker_sector(ticker: str) -> str:
    try:
        import factors_plus
        # 只读已缓存的 info, 避免为板块因子额外发起 yfinance .info 请求 (拖慢大扫描)
        info = factors_plus._INFO_CACHE.get(ticker)
        if not info:
            return ""
        return info.get("sector") or ""
    except Exception:
        return ""


def _us_score(ticker: str) -> tuple:
    scores = _cached("us_sector_scores", _us_sector_scores)
    if not scores:
        return 50.0, {}
    sector = _us_ticker_sector(ticker)
    if not sector or sector not in scores:
        return 50.0, {"板块": sector or "未知"}
    return scores[sector], {"板块": sector}


# ------------------------------------------------------------------ A 股
def _a_board_scores() -> dict:
    """返回 {行业板块名: 热度分}。用东财行业板块当日涨跌幅排名。"""
    def _work():
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return {}
        name_col = "板块名称" if "板块名称" in df.columns else df.columns[1]
        chg_col = "涨跌幅" if "涨跌幅" in df.columns else None
        if chg_col is None:
            return {}
        pairs = []
        for _, r in df.iterrows():
            try:
                pairs.append((str(r[name_col]), float(r[chg_col])))
            except Exception:
                continue
        return _rank_scores(pairs)

    res = _run_timeout(_work, timeout=15.0)
    return res or {}


def _a_ticker_board(code6: str) -> str:
    def _work():
        import akshare as ak
        df = ak.stock_individual_info_em(symbol=code6)
        if df is None or df.empty:
            return ""
        # df 为 item/value 两列
        cols = list(df.columns)
        ic, vc = cols[0], cols[1]
        for _, r in df.iterrows():
            if str(r[ic]).strip() == "行业":
                return str(r[vc]).strip()
        return ""

    res = _run_timeout(lambda: _cached(f"a_board_{code6}", _work, ttl=86400), timeout=12.0)
    return res or ""


def _a_share_score(ticker: str, heavy_ok: bool = True) -> tuple:
    scores = _cached("a_board_scores", _a_board_scores)
    if not scores:
        return 50.0, {}
    if not heavy_ok:
        return 50.0, {}      # 大扫描时跳过逐股行业查询, 保持速度
    code6 = ticker.split(".")[0]
    board = _a_ticker_board(code6)
    if not board:
        return 50.0, {"板块": "未知"}
    # 板块名可能与个股行业名有细微差异, 做包含匹配兜底
    if board in scores:
        return scores[board], {"板块": board}
    for k, v in scores.items():
        if board in k or k in board:
            return v, {"板块": k}
    return 50.0, {"板块": board}


# ------------------------------------------------------------------ 入口
def sector_score(ticker: str, name: str = "", d=None, heavy_ok: bool = True) -> tuple:
    """返回 (0~100 板块热度分, 明细dict)。取不到一律中性 50。
    heavy_ok=False 时 (大扫描) A股跳过逐股行业查询以保速度。"""
    if not enabled():
        return 50.0, {}
    try:
        if ticker.endswith((".SS", ".SZ")):
            return _a_share_score(ticker, heavy_ok=heavy_ok)
        return _us_score(ticker)
    except Exception:
        return 50.0, {}


if __name__ == "__main__":
    for t in ["NVDA", "XOM", "603990.SS", "600519.SS"]:
        print(t, sector_score(t))
