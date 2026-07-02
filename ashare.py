"""
A股选股池 (ashare.py)
=====================
用与美股相同的多因子引擎分析 A 股 (沪市 .SS / 深市 .SZ)。

数据源: yfinance (代码加交易所后缀)。说明:
  - 价格、技术指标、基本面(PE/营收增速) 可用;
  - 分析师评级/目标价 部分个股有, 缺失时该因子取中性 50;
  - 英文新闻情绪对 A 股不适用, 故默认 use_news=False。

覆盖各行业龙头 (沪深300 核心成分为主)。可在此增删。
"""
from __future__ import annotations
import pandas as pd
import engine

# 行业龙头 (代码: 名称)。后缀 .SS=上交所 .SZ=深交所
A_UNIVERSE = {
    "白酒/消费": {
        "600519.SS": "贵州茅台", "000858.SZ": "五粮液", "000568.SZ": "泸州老窖",
        "600887.SS": "伊利股份", "603288.SS": "海天味业", "000333.SZ": "美的集团",
        "000651.SZ": "格力电器",
    },
    "金融": {
        "601318.SS": "中国平安", "600036.SS": "招商银行", "000001.SZ": "平安银行",
        "601166.SS": "兴业银行", "600030.SS": "中信证券", "601628.SS": "中国人寿",
    },
    "新能源/电力设备": {
        "300750.SZ": "宁德时代", "002594.SZ": "比亚迪", "601012.SS": "隆基绿能",
        "300274.SZ": "阳光电源", "002460.SZ": "赣锋锂业", "600905.SS": "三峡能源",
    },
    "半导体/电子": {
        "688981.SS": "中芯国际", "603501.SS": "韦尔股份", "002371.SZ": "北方华创",
        "300782.SZ": "卓胜微", "002475.SZ": "立讯精密",
    },
    "医药": {
        "600276.SS": "恒瑞医药", "603259.SS": "药明康德", "300760.SZ": "迈瑞医疗",
        "000538.SZ": "云南白药", "600196.SS": "复星医药",
    },
    "工业/资源": {
        "601899.SS": "紫金矿业", "600028.SS": "中国石化", "601857.SS": "中国石油",
        "600585.SS": "海螺水泥", "601390.SS": "中国中铁", "600019.SS": "宝钢股份",
    },
}


def _flatten(pool: dict) -> dict[str, str]:
    out = {}
    for grp in pool.values():
        out.update(grp)
    return out


# 代码 -> 中文名 (已知龙头), 供搜索时回填名称
A_NAME = _flatten(A_UNIVERSE)


def normalize_code(raw: str) -> str:
    """把用户输入的 A 股代码归一化为带交易所后缀的形式。

    支持:  600519 / 600519.SS / sh600519 / 000858 / 000858.SZ / sz000858
    规则:  6/5/9 开头 -> 上交所 .SS;  0/2/3 开头 -> 深交所 .SZ
    """
    s = (raw or "").strip().upper().replace(" ", "")
    if not s:
        return ""
    # 已带后缀
    if s.endswith(".SS") or s.endswith(".SZ"):
        return s
    # sh/sz 前缀
    if s.startswith("SH") and s[2:].isdigit():
        return s[2:] + ".SS"
    if s.startswith("SZ") and s[2:].isdigit():
        return s[2:] + ".SZ"
    # 纯数字
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 6:
        if digits[0] in ("6", "5", "9"):
            return digits + ".SS"
        if digits[0] in ("0", "2", "3"):
            return digits + ".SZ"
        return digits + ".SS"
    return s  # 无法识别, 原样返回


def theme_of(code: str) -> str:
    for theme, grp in A_UNIVERSE.items():
        if code in grp:
            return theme
    return ""


def screen(exclude: set[str] | None = None, period: str = "1y",
           use_fundamentals: bool = True, top: int = 15,
           use_news: bool = True) -> pd.DataFrame:
    """A 股扫描。use_news=True 时用中文新闻情绪 (akshare)。"""
    exclude = exclude or set()
    wl = {k: v for k, v in _flatten(A_UNIVERSE).items() if k not in exclude}
    res = engine.analyze(wl, period=period, use_news=use_news,
                         use_fundamentals=use_fundamentals)
    t = res["table"].copy()
    t["主题"] = t["代码"].map(theme_of)
    # A 股价格用人民币, 列名保持一致
    return t.head(top) if top else t


if __name__ == "__main__":
    print("=== A股龙头 Top15 ===")
    df = screen(top=15)
    cols = ["代码", "名称", "主题", "综合分", "信号", "趋势", "基本面", "分析师", "现价", "建议仓位%"]
    print(df[[c for c in cols if c in df.columns]].to_string(index=False))
