"""
新闻情绪模块 (news.py)
=====================
抓取个股新闻 (yfinance) + VADER 情绪分析 + 金融词典覆盖。
产出 0~100 的「新闻情绪」因子, 越高越正面。

VADER 通用模型不懂金融词 (plunge/beat/downgrade 等), 这里用金融词典覆盖修正,
并对越新的新闻给越高权重 (时间衰减)。
"""
from __future__ import annotations
import datetime as dt
import numpy as np
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# 金融领域词典覆盖 (VADER 默认 lexicon 缺这些金融语义)
_FIN_LEXICON = {
    # 利空
    "plunge": -3.0, "plunges": -3.0, "plummet": -3.2, "slump": -2.5, "slide": -2.0,
    "tumble": -2.8, "tumbles": -2.8, "hammered": -2.6, "crash": -3.5, "selloff": -2.5,
    "sell-off": -2.5, "downgrade": -2.8, "downgraded": -2.8, "miss": -2.2, "misses": -2.2,
    "cut": -1.5, "cuts": -1.5, "lawsuit": -2.0, "probe": -1.8, "recall": -2.2,
    "warning": -1.8, "weak": -1.8, "bearish": -2.5, "loss": -1.8, "losses": -1.8,
    "layoff": -2.0, "layoffs": -2.0, "fraud": -3.5, "bankruptcy": -3.8, "halt": -2.0,
    "underperform": -2.0, "overvalued": -1.5, "falling": -1.8, "drop": -1.8, "drops": -1.8,
    # 利好
    "surge": 3.0, "surges": 3.0, "soar": 3.2, "soars": 3.2, "rally": 2.5, "rallies": 2.5,
    "jump": 2.2, "jumps": 2.2, "beat": 2.5, "beats": 2.5, "upgrade": 2.8, "upgraded": 2.8,
    "record": 2.0, "outperform": 2.5, "bullish": 2.8, "buyback": 2.0, "breakout": 2.2,
    "profit": 1.8, "growth": 1.8, "soaring": 3.0, "gains": 2.0, "rebound": 2.2,
    "raised": 1.8, "boost": 2.0, "boosts": 2.0, "tops": 2.0, "wins": 2.0, "approval": 2.0,
    "milestone": 1.8, "partnership": 1.5, "expands": 1.5, "undervalued": 1.5,
}

_sia = SentimentIntensityAnalyzer()
_sia.lexicon.update(_FIN_LEXICON)


def _extract(item: dict) -> dict | None:
    c = item.get("content", item) or {}
    title = c.get("title") or item.get("title")
    if not title:
        return None
    summary = c.get("summary") or c.get("description") or ""
    pub = c.get("pubDate") or c.get("providerPublishTime") or ""
    # 解析时间
    when = None
    if isinstance(pub, str) and pub:
        try:
            when = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            when = None
    link = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link", "")
    pub_name = (c.get("provider") or {}).get("displayName", "") if isinstance(c.get("provider"), dict) else ""
    return {"title": title, "summary": summary, "when": when, "link": link, "source": pub_name}


def fetch_news(ticker, max_items: int = 10) -> list[dict]:
    """抓取并打分单只股票的新闻. 返回带 sentiment 的列表 (按时间倒序)。"""
    import yfinance as yf
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        return []
    items = []
    now = dt.datetime.now(dt.timezone.utc)
    for it in raw[:max_items]:
        e = _extract(it)
        if not e:
            continue
        text = f"{e['title']}. {e['summary']}"
        score = _sia.polarity_scores(text)["compound"]   # -1~1
        # 时间衰减权重: 3 天半衰期
        age_days = (now - e["when"]).total_seconds() / 86400 if e["when"] else 3
        weight = 0.5 ** (max(age_days, 0) / 3)
        e["sentiment"] = round(score, 3)
        e["weight"] = round(weight, 3)
        items.append(e)
    return items


def sentiment_factor(ticker) -> tuple[float, list[dict]]:
    """返回 (0~100 情绪分, 新闻列表)。无新闻时返回中性 50。
    若启用 LLM_SENTIMENT 且配置了大模型 key, 再叠一层 LLM 语义情绪 (补充因子)。"""
    items = fetch_news(ticker)
    if not items:
        return 50.0, []
    wsum = sum(i["weight"] for i in items) or 1
    avg = sum(i["sentiment"] * i["weight"] for i in items) / wsum   # -1~1
    # 映射到 0~100, 放大斜率让信号更明显
    factor = float(np.clip(50 + avg * 80, 0, 100))
    try:
        import llm
        heads = [f"{i['title']}. {i.get('summary', '')}" for i in items]
        factor = llm.blend_llm_sentiment(heads, factor, name=str(ticker))
    except Exception:
        pass
    return round(factor, 1), items


if __name__ == "__main__":
    for tk in ["NVDA", "TSLA", "SPCX"]:
        f, items = sentiment_factor(tk)
        print(f"\n{tk}  新闻情绪分: {f}  ({len(items)} 条)")
        for i in items[:4]:
            d = i["when"].strftime("%m-%d") if i["when"] else "??"
            print(f"  [{i['sentiment']:+.2f}] {d} {i['title'][:65]}")
