# -*- coding: utf-8 -*-
"""富途 AI 新闻源 (futu_news.py)
================================
调用富途公开的新闻搜索网关 (ai-news-search.futunn.com), 为美股/港股/A股提供
统一、稳定、多市场的新闻标题, 供"新闻情绪"因子打分。

优点 (相对 yfinance/akshare):
  - 一个接口覆盖美/港/A 三大市场, 中英文都能搜;
  - 无需 API Key, 无需本地 OpenD 网关 -> Streamlit Cloud 也能用;
  - 比 yfinance 新闻更全更新, 不易空/限流。

情绪打分复用 news.py 的金融版 VADER (含金融词典), 并可叠加 llm.py 的
大模型情绪层 (LLM_SENTIMENT=1 时)。任何一步失败都安全回退, 不影响主流程。

来源: 富途官方 "Futu Skills Hub" 的 futu-news-search 技能所用的公开网关。
关闭: 设环境变量 FUTU_NEWS=0。
"""
from __future__ import annotations
import datetime as dt
import os
import re

import numpy as np

_BASE = "https://ai-news-search.futunn.com"
_UA = "futunn-news-search/0.0.2 (Skill)"
_HTML = re.compile(r"<[^>]+>")


def enabled() -> bool:
    return str(os.getenv("FUTU_NEWS", "1")).lower() not in ("0", "false", "no", "off")


def _clean(s: str) -> str:
    s = _HTML.sub("", s or "")
    return (s.replace("&amp;", "&").replace("&quot;", '"')
             .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">").strip())


def _keyword(ticker: str, name: str = "") -> str:
    """挑一个最利于命中的搜索词。
       美股: 直接用 ticker (如 NVDA); 港股/A股: 优先中文名, 否则用去后缀代码。"""
    t = str(ticker)
    if t.endswith((".SS", ".SZ", ".HK")):
        return name or re.split(r"[.\s]", t)[0]
    return t or name


def fetch_news(ticker: str, name: str = "", size: int = 15,
               lang: str = "en", timeout: int = 12) -> list[dict]:
    """抓取单只股票的新闻标题 (按时间倒序), 带时间衰减权重。失败返回 []。"""
    import requests
    kw = _keyword(ticker, name)
    if not kw:
        return []
    try:
        r = requests.get(
            f"{_BASE}/news_search",
            params={"keyword": kw, "size": max(1, min(int(size), 50)),
                    "lang": lang, "sort_type": 2},
            headers={"User-Agent": _UA}, timeout=timeout)
        r.raise_for_status()
        obj = r.json()
    except Exception:
        return []
    if not isinstance(obj, dict) or obj.get("code") != 0:
        return []
    now = dt.datetime.now(dt.timezone.utc)
    items = []
    for it in (obj.get("data") or [])[:size]:
        title = _clean(it.get("title"))
        if not title:
            continue
        when = None
        try:
            when = dt.datetime.fromtimestamp(int(it.get("publish_time")), dt.timezone.utc)
        except (ValueError, TypeError):
            when = None
        age_days = (now - when).total_seconds() / 86400 if when else 3
        weight = 0.5 ** (max(age_days, 0) / 3)   # 3 天半衰期, 与 news.py 一致
        items.append({"title": title, "summary": "", "when": when,
                      "weight": round(weight, 3), "link": it.get("url", ""),
                      "source": "富途"})
    return items


def _score(items: list[dict]) -> None:
    """就地给每条新闻打 -1~1 情绪分 (复用 news.py 的金融 VADER)。"""
    try:
        import news as _n
        for i in items:
            i["sentiment"] = round(_n._sia.polarity_scores(i["title"])["compound"], 3)
    except Exception:
        for i in items:
            i.setdefault("sentiment", 0.0)


def sentiment_factor(ticker: str, name: str = "") -> tuple[float, list[dict]]:
    """返回 (0~100 情绪分, 新闻列表)。无新闻 -> (50, [])。
       0~100 映射与 news.py 保持一致; 可叠加 LLM 情绪层。"""
    items = fetch_news(ticker, name)
    if not items:
        return 50.0, []
    _score(items)
    wsum = sum(i["weight"] for i in items) or 1
    avg = sum(i["sentiment"] * i["weight"] for i in items) / wsum   # -1~1
    factor = float(np.clip(50 + avg * 80, 0, 100))
    try:
        import llm
        factor = llm.blend_llm_sentiment([i["title"] for i in items],
                                         factor, name=name or str(ticker))
    except Exception:
        pass
    return round(factor, 1), items


if __name__ == "__main__":
    for tk, nm in [("NVDA", "英伟达"), ("AAPL", "苹果"),
                   ("600519.SS", "贵州茅台"), ("00700.HK", "腾讯控股")]:
        f, items = sentiment_factor(tk, nm)
        print(f"\n{tk} ({nm})  富途新闻情绪: {f}  ({len(items)} 条)")
        for i in items[:4]:
            d = i["when"].strftime("%m-%d") if i["when"] else "??"
            print(f"  [{i.get('sentiment',0):+.2f}] {d} {i['title'][:70]}")