"""
A股中文新闻情绪 (cn_news.py)
===========================
akshare 抓东方财富个股新闻 + 中文金融情绪词典打分。
产出 0~100 情绪因子, 思路与英文版 news.py 一致 (时间衰减加权)。

为什么用词典而非通用情感模型: 通用中文情感库(如SnowNLP)训练自购物评论,
不懂"减持/商誉减值/涨停"等金融语义; 这里用金融领域词典更可靠。
"""
from __future__ import annotations
import datetime as dt
import re
import numpy as np

# 中文金融情绪词典 (词: 权重)。可继续扩充。
_POS = {
    "涨停": 3.0, "大涨": 2.5, "涨幅": 1.2, "创新高": 2.5, "新高": 2.0, "上涨": 1.5,
    "增长": 1.8, "增持": 2.2, "回购": 2.2, "分红": 1.8, "派息": 1.5, "盈利": 1.8,
    "净利润增长": 2.8, "业绩预增": 3.0, "预增": 2.5, "超预期": 2.8, "中标": 2.2,
    "签约": 1.5, "订单": 1.5, "突破": 1.8, "利好": 2.5, "看好": 2.0, "买入": 2.0,
    "增资": 1.5, "扩产": 1.8, "提价": 1.8, "复苏": 1.8, "龙头": 1.2, "领涨": 2.2,
    "受益": 1.5, "放量": 1.0, "强势": 1.8, "上调": 1.8, "高增长": 2.5, "翻倍": 2.5,
    "中标金额": 2.0, "战略合作": 1.5, "获批": 2.0, "认可": 1.2, "扭亏": 2.5,
}
_NEG = {
    "跌停": -3.0, "大跌": -2.5, "暴跌": -3.2, "下跌": -1.5, "下滑": -1.8, "下降": -1.5,
    "减持": -2.5, "亏损": -2.5, "净利润下滑": -2.8, "业绩预减": -3.0, "预减": -2.5,
    "低于预期": -2.5, "不及预期": -2.5, "退市": -3.8, "违规": -2.8, "处罚": -2.5,
    "罚款": -2.2, "诉讼": -2.0, "立案": -2.8, "调查": -2.0, "商誉减值": -2.8,
    "减值": -2.0, "质押": -1.5, "爆雷": -3.5, "利空": -2.5, "看空": -2.2, "卖出": -2.0,
    "下调": -1.8, "预亏": -3.0, "停牌": -1.8, "造假": -3.8, "财务造假": -3.8,
    "违约": -2.8, "破产": -3.8, "裁员": -2.0, "下修": -2.2, "承压": -1.8, "重挫": -2.8,
    "跌幅": -1.2, "套现": -1.8, "解禁": -1.2, "风险提示": -1.5,
}


def _score_text(text: str) -> float | None:
    """统计金融正/负词, 归一到 -1~1。无命中返回 None。"""
    pos = sum(w * len(re.findall(re.escape(k), text)) for k, w in _POS.items())
    neg = sum(w * len(re.findall(re.escape(k), text)) for k, w in _NEG.items())
    if pos == 0 and neg == 0:
        return None
    raw = pos + neg
    return float(np.tanh(raw / 4.0))      # 压缩到 -1~1


def _to_symbol(code: str) -> str:
    """600519.SS / 000858.SZ -> 600519 / 000858 (东方财富用纯数字)。"""
    return re.split(r"[.\s]", code)[0]


def fetch_news(code: str, max_items: int = 10) -> list[dict]:
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=_to_symbol(code))
    except Exception:
        return []
    if df is None or len(df) == 0:
        return []
    now = dt.datetime.now()
    items = []
    for _, r in df.head(max_items).iterrows():
        title = str(r.get("新闻标题", ""))
        content = str(r.get("新闻内容", ""))
        text = f"{title}。{content}"
        sc = _score_text(text)
        if sc is None:
            sc = 0.0
        pub = str(r.get("发布时间", ""))
        when = None
        try:
            when = dt.datetime.fromisoformat(pub)
        except (ValueError, TypeError):
            when = None
        age_days = (now - when).total_seconds() / 86400 if when else 3
        weight = 0.5 ** (max(age_days, 0) / 3)
        items.append({"title": title, "sentiment": round(sc, 3),
                      "weight": round(weight, 3), "when": when,
                      "source": str(r.get("文章来源", "")),
                      "link": str(r.get("新闻链接", ""))})
    return items


def sentiment_factor(code: str) -> tuple[float, list[dict]]:
    items = fetch_news(code)
    if not items:
        return 50.0, []
    wsum = sum(i["weight"] for i in items) or 1
    avg = sum(i["sentiment"] * i["weight"] for i in items) / wsum
    factor = float(np.clip(50 + avg * 80, 0, 100))
    try:
        import llm
        heads = [i["title"] for i in items]
        factor = llm.blend_llm_sentiment(heads, factor, name=str(code))
    except Exception:
        pass
    return round(factor, 1), items


if __name__ == "__main__":
    for code in ["600519.SS", "300750.SZ", "002594.SZ"]:
        f, items = sentiment_factor(code)
        print(f"\n{code}  中文新闻情绪: {f}  ({len(items)}条)")
        for i in items[:4]:
            d = i["when"].strftime("%m-%d") if i["when"] else "??"
            print(f"  [{i['sentiment']:+.2f}] {d} {i['title'][:45]}")
