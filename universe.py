"""
高科技选股池 (universe.py)
=========================
在你持仓之外, 扫描一篮子高科技龙头 / 高成长股, 用同一套 9 因子打分排名,
推荐综合分最高的买入候选。

主题覆盖: AI 算力 / 半导体 / 云与软件 / 互联网平台 / 新能源车 / 网络安全 / 金融科技。
可在 app 里增删。
"""
from __future__ import annotations
import pandas as pd
import engine

# 按主题分组的高科技股票池 (美股)
TECH_UNIVERSE = {
    "AI算力/半导体": {
        "NVDA": "英伟达", "AMD": "超威半导体", "AVGO": "博通", "TSM": "台积电",
        "MU": "美光", "SNDK": "闪迪", "MRVL": "迈威尔", "ARM": "Arm",
        "SMCI": "超微电脑", "ASML": "阿斯麦", "LRCX": "拉姆研究", "AMAT": "应用材料",
        "QCOM": "高通", "INTC": "英特尔", "TXN": "德州仪器",
    },
    "云与软件": {
        "MSFT": "微软", "GOOGL": "谷歌", "AMZN": "亚马逊", "CRM": "Salesforce",
        "ORCL": "甲骨文", "NOW": "ServiceNow", "SNOW": "Snowflake",
        "PLTR": "Palantir", "ADBE": "Adobe", "PANW": "Palo Alto",
        "CRWD": "CrowdStrike", "DDOG": "Datadog", "NET": "Cloudflare",
    },
    "互联网/平台": {
        "META": "Meta", "AAPL": "苹果", "NFLX": "奈飞", "UBER": "优步",
        "SHOP": "Shopify", "ABNB": "爱彼迎", "SPOT": "声田",
    },
    "新能源车/光通信": {
        "TSLA": "特斯拉", "LITE": "Lumentum", "COHR": "相干", "RIVN": "Rivian",
        "ON": "安森美", "ENPH": "Enphase",
    },
    "金融科技/其他": {
        "SPCX": "SpaceX", "COIN": "Coinbase", "HOOD": "Robinhood",
        "XYZ": "Block", "PYPL": "PayPal",
    },
}


def flat_universe() -> dict[str, str]:
    out = {}
    for grp in TECH_UNIVERSE.values():
        out.update(grp)
    return out


def theme_of(ticker: str) -> str:
    for theme, grp in TECH_UNIVERSE.items():
        if ticker in grp:
            return theme
    return ""


def screen(exclude: set[str] | None = None, period: str = "1y",
           use_news: bool = False, use_fundamentals: bool = True,
           top: int = 15) -> pd.DataFrame:
    """扫描股票池, 返回排名表。默认关新闻(池子大, 提速), 保留基本面。"""
    exclude = exclude or set()
    wl = {k: v for k, v in flat_universe().items() if k not in exclude}
    res = engine.analyze(wl, period=period, use_news=use_news,
                         use_fundamentals=use_fundamentals)
    t = res["table"].copy()
    t["主题"] = t["代码"].map(theme_of)
    return t.head(top) if top else t


if __name__ == "__main__":
    df = screen(top=15)
    cols = ["代码", "名称", "主题", "综合分", "信号", "基本面", "分析师", "现价", "建议仓位%"]
    print(df[cols].to_string(index=False))
