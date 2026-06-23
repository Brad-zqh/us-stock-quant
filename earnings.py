"""
财报日临近提醒 (earnings.py)
===========================
财报前后股价波动剧烈, 容易"追高"被套。本模块给出下次财报日与剩余天数,
临近(默认<=7天)时在界面/推送里标 ⚠️ 提醒谨慎。

美股: yfinance get_earnings_dates (可靠)。
A股: akshare 业绩预约披露时间 (有则用, 慢/缺失时返回 None)。
因 akshare 较慢, 仅对自选股 + 个股详情计算, 不用于大池子扫描。
"""
from __future__ import annotations
import datetime as dt

_CACHE: dict[str, dict] = {}


def _us_next(ticker: str):
    import yfinance as yf
    try:
        ed = yf.Ticker(ticker).get_earnings_dates(limit=12)
        if ed is None or len(ed) == 0:
            return None
        now = dt.datetime.now(ed.index.tz)
        future = ed[ed.index > now]
        return future.index.min().to_pydatetime() if len(future) else None
    except Exception:
        return None


def _a_next(code: str):
    """A股下次预约披露日。akshare 接口不稳, 失败返回 None。"""
    try:
        import akshare as ak
        num = code.split(".")[0]
        # 预约披露时间表 (按报告期), 取最近未来日期
        for q in _recent_report_periods():
            try:
                df = ak.stock_yysj_em(symbol="沪深A股", date=q)
            except Exception:
                continue
            if df is None or len(df) == 0:
                continue
            col_code = next((c for c in df.columns if "代码" in c), None)
            col_date = next((c for c in df.columns if "预约" in c or "披露" in c or "日期" in c), None)
            if not col_code or not col_date:
                continue
            row = df[df[col_code].astype(str).str.zfill(6) == num]
            if len(row):
                try:
                    d = dt.datetime.fromisoformat(str(row.iloc[0][col_date]))
                    if d > dt.datetime.now():
                        return d
                except (ValueError, TypeError):
                    continue
        return None
    except Exception:
        return None


def _recent_report_periods() -> list[str]:
    """最近几个报告期末 (YYYYMMDD), 用于查预约披露。"""
    today = dt.datetime.now()
    y = today.year
    cands = [f"{y}0331", f"{y}0630", f"{y}0930", f"{y-1}1231", f"{y}1231"]
    return cands


def next_earnings(ticker: str) -> dict | None:
    """返回 {date, days, soon} 或 None。soon=未来7天内。"""
    if ticker in _CACHE:
        return _CACHE[ticker]
    if ticker.endswith((".SS", ".SZ")):
        nxt = _a_next(ticker)
    else:
        nxt = _us_next(ticker)
    res = None
    if nxt is not None:
        nxt_naive = nxt.replace(tzinfo=None)
        days = (nxt_naive.date() - dt.date.today()).days
        res = {"date": nxt_naive.strftime("%Y-%m-%d"), "days": days,
               "soon": 0 <= days <= 7}
    _CACHE[ticker] = res
    return res


def warn_text(ticker: str) -> str:
    """给推送/界面用的一行提醒, 无则空串。"""
    e = next_earnings(ticker)
    if not e:
        return ""
    if e["soon"]:
        return f"⚠️ {ticker} {e['days']}天后({e['date']})财报, 谨慎追高"
    return ""


if __name__ == "__main__":
    for tk in ["NVDA", "AAPL", "TSLA", "600519.SS"]:
        print(tk, next_earnings(tk))
