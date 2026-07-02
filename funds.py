"""指数基金 / ETF 池 (funds.py)
==============================
把常见的美国、中国指数基金(ETF)按主题归类, 复用 universe.screen() 做多因子排名,
并可对单只基金调用 engine.analyze() 出个股(基金)详情。

  - US_INDEX: 美国上市 ETF (美元计价)。宽基 / 行业 / 债券黄金 / 主题。
  - CN_INDEX: A股上市 ETF (人民币计价, .SS/.SZ)。宽基 / 行业主题。

注意: ETF 没有"基本面/分析师/财报"因子, 打分主要看趋势/动量/技术面 + 大盘环境,
      适合做"指数择时/轮动"参考, 不是选股。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 美国指数 ETF (USD)
US_INDEX: dict[str, dict[str, str]] = {
    "宽基指数": {
        "SPY": "标普500 SPDR",
        "VOO": "标普500 (先锋)",
        "IVV": "标普500 (iShares)",
        "QQQ": "纳斯达克100",
        "QQQM": "纳指100 (低费率)",
        "DIA": "道琼斯工业",
        "IWM": "罗素2000 小盘",
        "VTI": "美国全市场",
        "VT": "全球全市场",
        "RSP": "标普500 等权",
    },
    "行业板块": {
        "XLK": "科技板块",
        "SMH": "半导体 (VanEck)",
        "SOXX": "半导体 (iShares)",
        "XLF": "金融板块",
        "XLE": "能源板块",
        "XLV": "医疗板块",
        "XLY": "可选消费",
        "XLP": "必需消费",
        "XLI": "工业板块",
        "XLU": "公用事业",
        "XLRE": "房地产",
        "XLB": "原材料",
        "XLC": "通信服务",
    },
    "债券·黄金·大宗": {
        "TLT": "20年+美国国债",
        "IEF": "7-10年美国国债",
        "SHY": "1-3年美国国债",
        "LQD": "投资级公司债",
        "HYG": "高收益债",
        "GLD": "黄金",
        "SLV": "白银",
        "USO": "原油",
        "DBC": "综合大宗商品",
    },
    "主题·成长": {
        "ARKK": "方舟颠覆创新",
        "IBB": "生物科技",
        "IGV": "软件",
        "SKYY": "云计算",
        "ICLN": "清洁能源",
        "TAN": "太阳能",
        "XBI": "生物科技 (等权)",
    },
    "中国相关 (美上市)": {
        "FXI": "中国大盘 (富时中国50)",
        "MCHI": "MSCI 中国",
        "ASHR": "沪深300 (美上市)",
        "KWEB": "中概互联网",
        "CQQQ": "中国科技",
        "PGJ": "金龙中国",
    },
}

# ---------------------------------------------------------------- 中国指数 ETF (¥, A股)
CN_INDEX: dict[str, dict[str, str]] = {
    "宽基指数": {
        "510300.SS": "沪深300ETF",
        "510500.SS": "中证500ETF",
        "510050.SS": "上证50ETF",
        "159919.SZ": "沪深300ETF(深)",
        "159915.SZ": "创业板ETF",
        "588000.SS": "科创50ETF",
        "588080.SS": "科创板50ETF",
        "512100.SS": "中证1000ETF",
        "510880.SS": "红利ETF",
        "515180.SS": "中证100ETF",
    },
    "科技·半导体": {
        "512480.SS": "半导体ETF",
        "159995.SZ": "芯片ETF",
        "515000.SS": "科技ETF",
        "515230.SS": "软件ETF",
        "159801.SZ": "半导体(深)",
        "512720.SS": "计算机ETF",
    },
    "新能源·制造": {
        "515030.SS": "新能源车ETF",
        "516160.SS": "新能源ETF",
        "515790.SS": "光伏ETF",
        "159611.SZ": "电力ETF",
        "512400.SS": "有色金属ETF",
        "512660.SS": "军工ETF",
    },
    "金融·地产": {
        "512880.SS": "证券ETF",
        "512000.SS": "券商ETF",
        "512800.SS": "银行ETF",
        "512200.SS": "房地产ETF",
        "510230.SS": "金融ETF",
    },
    "消费·医药": {
        "512690.SS": "酒ETF",
        "159928.SZ": "消费ETF",
        "512010.SS": "医药ETF",
        "512170.SS": "医疗ETF",
        "159992.SZ": "创新药ETF",
        "515170.SS": "食品饮料ETF",
    },
}


def _flatten(pool: dict) -> dict[str, str]:
    out = {}
    for grp in pool.values():
        out.update(grp)
    return out


# 代码 -> 名称 (供单只基金搜索时回填名称)
US_FUND_NAME = _flatten(US_INDEX)
CN_FUND_NAME = _flatten(CN_INDEX)
FUND_NAME = {**US_FUND_NAME, **CN_FUND_NAME}


def search_fund(query: str, market: str = "US", limit: int = 12) -> list[tuple]:
    """在基金池里按代码或中文名模糊搜索。返回 [(code, name), ...]。"""
    q = (query or "").strip()
    if not q:
        return []
    pool = US_FUND_NAME if market == "US" else CN_FUND_NAME
    ql = q.lower()
    exact, starts, contains = [], [], []
    for code, name in pool.items():
        cl, nl = code.lower(), name.lower()
        if cl == ql or code.split(".")[0].lower() == ql:
            exact.append((code, name))
        elif nl.startswith(ql) or cl.startswith(ql):
            starts.append((code, name))
        elif ql in nl or ql in cl:
            contains.append((code, name))
    out, seen = [], set()
    for c, n in exact + starts + contains:
        if c not in seen:
            out.append((c, n))
            seen.add(c)
    return out[:limit]


if __name__ == "__main__":
    print("美国指数主题:", list(US_INDEX.keys()))
    print("中国指数主题:", list(CN_INDEX.keys()))
    print("搜 '纳斯达克':", search_fund("纳斯达克", "US"))
    print("搜 '半导体' CN:", search_fund("半导体", "CN"))
