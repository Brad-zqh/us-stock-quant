"""行情数据层 (quotes.py)
========================
统一的历史行情入口, 优先富途 OpenD, 失败/无网关时自动回退 yfinance。

设计目标:
  - 本地跑 (FutuOpenD 已开) → 走富途, 数据稳、免 yfinance 限流/delisted。
  - 云端 Streamlit (无 OpenD) → 静默回退 yfinance, 行为与改造前完全一致 (零影响)。
  - 对上层完全透明: fetch() 签名与返回结构和原 engine.fetch 一致。

返回: {ticker: OHLCV DataFrame}
  - 列: Open / High / Low / Close / Volume
  - index: DatetimeIndex (升序)
  - 前复权 (与 yfinance auto_adjust 对齐)

ticker 沿用 yfinance 写法 (AAPL / 600519.SS / QQQ), 内部转富途代码 (US.AAPL / SH.600519)。
纯数据工具, 不构成投资建议。
"""
from __future__ import annotations

import os
import datetime as dt

import pandas as pd
import yfinance as yf

# ----------------------------------------------------------------------------
# 富途连接 (惰性, 只探测一次; 连不上就本进程内永久回退 yfinance)
# ----------------------------------------------------------------------------
_ctx = None
_tried = False
_ok = False


def _get_ctx():
    """返回可用的 OpenQuoteContext, 或 None (未装 SDK / 网关没开 / 显式关闭)。"""
    global _ctx, _tried, _ok
    if _tried:
        return _ctx if _ok else None
    _tried = True

    if os.getenv("FUTU_QUOTE", "1") == "0":     # 显式关闭富途行情
        _ok = False
        return None
    try:
        from futu import OpenQuoteContext, RET_OK
        host = os.getenv("FUTU_HOST", "127.0.0.1")
        port = int(os.getenv("FUTU_PORT", "11111"))
        ctx = OpenQuoteContext(host=host, port=port)
        # 探测连接是否真的可用 (网关没开时构造不抛, 这里主动确认)
        ret, _ = ctx.get_global_state()
        if ret != RET_OK:
            try:
                ctx.close()
            except Exception:
                pass
            _ok = False
            return None
        _ctx = ctx
        _ok = True
        return ctx
    except Exception:
        _ok = False
        return None


# ----------------------------------------------------------------------------
# 代码 / 周期转换
# ----------------------------------------------------------------------------
def to_futu(ticker: str) -> str:
    """yfinance 写法 → 富途代码。 AAPL→US.AAPL, 600519.SS→SH.600519, 300750.SZ→SZ.300750。"""
    t = ticker.strip()
    if t.endswith(".SS"):
        return "SH." + t[:-3]
    if t.endswith(".SZ"):
        return "SZ." + t[:-3]
    if t.endswith(".HK"):
        return "HK." + t[:-3]
    if t.startswith(("US.", "SH.", "SZ.", "HK.")):     # 已是富途写法
        return t
    return "US." + t.upper()


_PERIOD_DAYS = {
    "1mo": 31, "3mo": 93, "6mo": 186, "1y": 366,
    "2y": 731, "3y": 1096, "5y": 1826, "10y": 3652, "max": 3660,
}


def _period_start(period: str) -> str:
    days = _PERIOD_DAYS.get(period, 731)
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


# ----------------------------------------------------------------------------
# 本地日缓存 (减少富途历史 K 线额度消耗, 同时加速 Streamlit 反复 rerun)
# ----------------------------------------------------------------------------
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".quote_cache")


def _cache_path(ticker: str, period: str) -> str:
    safe = ticker.replace(".", "_").replace("/", "_")
    return os.path.join(_CACHE_DIR, f"{safe}__{period}.pkl")


def _is_fresh_today(path: str) -> bool:
    try:
        mtime = dt.date.fromtimestamp(os.path.getmtime(path))
        return mtime == dt.date.today()
    except Exception:
        return False


# ----------------------------------------------------------------------------
# 富途取数
# ----------------------------------------------------------------------------
def _futu_one(ctx, code_futu: str, start: str, end: str) -> "pd.DataFrame | None":
    from futu import KLType, AuType, RET_OK
    frames = []
    ret, data, key = ctx.request_history_kline(
        code_futu, start=start, end=end, ktype=KLType.K_DAY,
        autype=AuType.QFQ, max_count=1000)
    if ret != RET_OK:
        return None
    frames.append(data)
    guard = 0
    while key and guard < 50:
        guard += 1
        ret, data, key = ctx.request_history_kline(
            code_futu, start=start, end=end, ktype=KLType.K_DAY,
            autype=AuType.QFQ, max_count=1000, page_req_key=key)
        if ret != RET_OK:
            break
        frames.append(data)

    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        return None
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    df["ts"] = pd.to_datetime(df["time_key"])
    df = (df.set_index("ts")[["Open", "High", "Low", "Close", "Volume"]]
            .apply(pd.to_numeric, errors="coerce")
            .dropna()
            .sort_index())
    df = df[~df.index.duplicated(keep="last")]
    return df if len(df) >= 5 else None


def _cached_or_futu(ctx, ticker: str, start: str, end: str,
                    period: str) -> "pd.DataFrame | None":
    path = _cache_path(ticker, period)
    if os.path.exists(path) and _is_fresh_today(path):
        try:
            return pd.read_pickle(path)
        except Exception:
            pass
    df = _futu_one(ctx, to_futu(ticker), start, end)
    if df is not None:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            df.to_pickle(path)
        except Exception:
            pass
    return df


# ----------------------------------------------------------------------------
# yfinance 回退 (与改造前 engine.fetch 逻辑一致)
# ----------------------------------------------------------------------------
def _yf_one(ticker: str, period: str, interval: str) -> "pd.DataFrame | None":
    """单票兜底: 批量 download 抽风时, 逐票用 Ticker.history 重试 (更稳)。"""
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
        df = df.dropna()
        if len(df) >= 5:
            return df[["Open", "High", "Low", "Close", "Volume"]]
    except Exception:
        return None
    return None


def _yf_fetch(tickers: list, period: str, interval: str) -> dict:
    out: dict = {}
    try:
        raw = yf.download(
            tickers, period=period, interval=interval,
            auto_adjust=True, progress=False, group_by="ticker", threads=True,
        )
        for t in tickers:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    df = raw[t] if t in raw.columns.get_level_values(0) else raw.droplevel(0, axis=1)
                else:
                    df = raw
                df = df.dropna()
                if len(df) >= 5:
                    out[t] = df
            except Exception:
                continue
    except Exception:
        pass

    # 批量没取到的, 逐票重试兜底 (yfinance 批量偶发限流, 单票 history 更稳)
    for t in tickers:
        if t not in out:
            df = _yf_one(t, period, interval)
            if df is not None:
                out[t] = df
    return out


# ----------------------------------------------------------------------------
# 对外统一入口
# ----------------------------------------------------------------------------
def fetch(tickers, period: str = "2y", interval: str = "1d") -> dict:
    """返回 {ticker: OHLCV DataFrame}. 优先富途, 缺失的用 yfinance 补齐。"""
    if isinstance(tickers, str):
        tickers = [tickers]
    tickers = list(dict.fromkeys(tickers))    # 去重保序

    # 非日线 (分钟/周/月) 直接走 yfinance: 富途分钟额度更贵, 保持简单
    if interval != "1d":
        return _yf_fetch(tickers, period, interval)

    out: dict = {}
    missing: list = []

    ctx = _get_ctx()
    if ctx is not None:
        start, end = _period_start(period), dt.date.today().isoformat()
        for t in tickers:
            df = None
            try:
                df = _cached_or_futu(ctx, t, start, end, period)
            except Exception:
                df = None
            if df is not None and len(df) >= 5:
                out[t] = df
            else:
                missing.append(t)
    else:
        missing = list(tickers)

    if missing:
        try:
            out.update(_yf_fetch(missing, period, interval))
        except Exception:
            pass
    return out


def source_status() -> dict:
    """给上层/诊断用: 当前行情源状态。"""
    ctx = _get_ctx()
    return {"futu_available": ctx is not None,
            "primary": "futu" if ctx is not None else "yfinance"}


if __name__ == "__main__":
    import sys
    ts = sys.argv[1:] or ["AAPL", "NVDA", "600519.SS", "QQQ"]
    print("行情源状态:", source_status())
    got = fetch(ts, period="6mo")
    for k, v in got.items():
        print(f"{k:12} {len(v):>4} 行  最新收盘 {v['Close'].iloc[-1]:.2f}  "
              f"({v.index[0].date()} → {v.index[-1].date()})")
    missing = [t for t in ts if t not in got]
    if missing:
        print("未取到:", missing)
