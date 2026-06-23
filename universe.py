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


# 美股非科技板块 (价值/防御/周期, 给科技仓位做分散)
US_SECTORS = {
    "金融": {
        "JPM": "摩根大通", "BAC": "美国银行", "GS": "高盛", "MS": "摩根士丹利",
        "V": "Visa", "MA": "万事达", "BRK-B": "伯克希尔", "BLK": "贝莱德", "AXP": "运通",
    },
    "医疗健康": {
        "LLY": "礼来", "UNH": "联合健康", "JNJ": "强生", "ABBV": "艾伯维",
        "MRK": "默克", "PFE": "辉瑞", "TMO": "赛默飞", "ISRG": "直觉外科", "AMGN": "安进",
    },
    "消费": {
        "COST": "好市多", "WMT": "沃尔玛", "PG": "宝洁", "KO": "可口可乐",
        "PEP": "百事", "MCD": "麦当劳", "NKE": "耐克", "SBUX": "星巴克", "HD": "家得宝",
    },
    "能源/工业": {
        "XOM": "埃克森美孚", "CVX": "雪佛龙", "CAT": "卡特彼勒", "GE": "通用电气",
        "BA": "波音", "HON": "霍尼韦尔", "RTX": "雷神", "DE": "迪尔", "LIN": "林德气体",
    },
    "通信/媒体": {
        "DIS": "迪士尼", "T": "AT&T", "VZ": "威瑞森", "CMCSA": "康卡斯特", "TMUS": "T-Mobile",
    },
}


def _flatten(pool: dict) -> dict[str, str]:
    out = {}
    for grp in pool.values():
        out.update(grp)
    return out


def flat_universe(pool: dict | None = None) -> dict[str, str]:
    return _flatten(pool or TECH_UNIVERSE)


def theme_of(ticker: str, pool: dict | None = None) -> str:
    for theme, grp in (pool or TECH_UNIVERSE).items():
        if ticker in grp:
            return theme
    return ""


def screen(exclude: set[str] | None = None, period: str = "1y",
           use_news: bool = False, use_fundamentals: bool = True,
           top: int = 15, pool: dict | None = None) -> pd.DataFrame:
    """扫描股票池, 返回排名表。pool 默认科技池, 可传 US_SECTORS。"""
    pool = pool or TECH_UNIVERSE
    exclude = exclude or set()
    wl = {k: v for k, v in _flatten(pool).items() if k not in exclude}
    res = engine.analyze(wl, period=period, use_news=use_news,
                         use_fundamentals=use_fundamentals)
    t = res["table"].copy()
    t["主题"] = t["代码"].map(lambda x: theme_of(x, pool))
    return t.head(top) if top else t


if __name__ == "__main__":
    print("=== 美股非科技板块 Top10 ===")
    df = screen(top=10, pool=US_SECTORS)
    cols = ["代码", "名称", "主题", "综合分", "信号", "基本面", "分析师", "现价", "建议仓位%"]
    print(df[cols].to_string(index=False))
