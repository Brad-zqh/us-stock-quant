"""标的解析 (resolve.py)
======================
把用户输入的 "代码 或 名称" 解析成可分析的股票代码：

  - search_us(q):     美股。用 Yahoo Finance 搜索接口, 支持代码(AAPL)或英文名(apple/nvidia)。
  - search_ashare(q): A股。用 akshare 全量 A股 代码-名称表(缓存), 支持 6位代码 或 中文名(茅台/比亚迪)。
                      akshare 不可用时回退到 ashare.A_UNIVERSE 里的龙头名单。

返回统一为候选列表, 供上层做下拉选择。
"""
from __future__ import annotations
import functools

import ashare
import universe

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

# 美股常见交易所优先级 (让 NASDAQ/NYSE 等美国上市排在前面)
_US_EXCH = {"NASDAQ": 0, "NYSE": 0, "NYSEArca": 1, "NYSE Arca": 1,
            "AMEX": 1, "NYSEAmerican": 1, "BATS": 2, "Cboe US": 2, "OTC": 5}


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (s or ""))


@functools.lru_cache(maxsize=1)
def _us_cn_map() -> dict:
    """美股代码 -> 中文名。精选池(即时可靠) + akshare 东财美股全量(尽力补充)。"""
    m = {}
    # 1) 本地精选池 (快、稳, 覆盖主要美股)
    try:
        m.update(universe._flatten(universe.TECH_UNIVERSE))
        m.update(universe._flatten(universe.US_SECTORS))
    except Exception:
        pass
    # 2) akshare 东方财富美股全量中文名 (海外服务器可能慢/超时, 失败则忽略)
    try:
        import akshare as ak
        df = ak.stock_us_spot_em()
        for _, r in df.iterrows():
            sym = str(r.get("代码", "")).split(".")[-1].upper()
            cn = str(r.get("名称", "")).strip()
            if sym and cn and sym not in m:
                m[sym] = cn
    except Exception:
        pass
    return m


def us_cn_name(symbol: str) -> str:
    """取美股中文名; 无中文名(或只有英文别名)时返回空串。"""
    cn = _us_cn_map().get((symbol or "").upper(), "")
    return cn if _has_cjk(cn) else ""


def search_us(query: str, limit: int = 8) -> list[tuple]:
    """返回 [(symbol, name_en, name_cn, exchange, quoteType), ...]。支持代码或英文名。"""
    q = (query or "").strip()
    if not q:
        return []
    try:
        import requests
        r = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": limit + 4, "newsCount": 0, "listsCount": 0},
            headers=_UA, timeout=8)
        quotes = r.json().get("quotes", [])
    except Exception:
        # 网络失败时: 若输入本身像代码, 直接当代码用
        if q.replace(".", "").replace("-", "").isalnum() and len(q) <= 6:
            sym = q.upper()
            return [(sym, sym, us_cn_name(sym), "", "EQUITY")]
        return []

    out = []
    for it in quotes:
        sym = it.get("symbol")
        if not sym:
            continue
        qt = it.get("quoteType", "")
        if qt not in ("EQUITY", "ETF"):
            continue
        name = it.get("shortname") or it.get("longname") or sym
        exch = it.get("exchDisp") or it.get("exchange") or ""
        out.append((sym, name, us_cn_name(sym), exch, qt))

    # 美国上市优先, 其次保持原有相关性顺序
    out.sort(key=lambda x: _US_EXCH.get(x[3], 3))
    return out[:limit]


@functools.lru_cache(maxsize=1)
def _a_list() -> tuple:
    """全量 A股 (代码带后缀, 名称)。akshare 优先, 失败回退龙头名单。缓存于进程生命周期。"""
    rows = []
    seen = set()
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()  # 列: code, name
        code_col = "code" if "code" in df.columns else df.columns[0]
        name_col = "name" if "name" in df.columns else df.columns[1]
        for _, r in df.iterrows():
            code = ashare.normalize_code(str(r[code_col]).zfill(6))
            name = str(r[name_col]).strip()
            if code and code not in seen:
                rows.append((code, name))
                seen.add(code)
    except Exception:
        pass
    # 合并龙头名单 (确保 akshare 挂掉时仍能搜到主要股)
    for code, name in ashare.A_NAME.items():
        if code not in seen:
            rows.append((code, name))
            seen.add(code)
    return tuple(rows)


def search_ashare(query: str, limit: int = 12) -> list[tuple]:
    """返回 [(code_with_suffix, name), ...]。支持 6位代码 或 中文名 模糊。"""
    q = (query or "").strip()
    if not q:
        return []
    digits = "".join(ch for ch in q if ch.isdigit())
    lst = _a_list()

    res = []
    if digits:  # 按代码匹配 (含部分匹配)
        exact = ashare.normalize_code(digits) if len(digits) == 6 else ""
        for code, name in lst:
            if code == exact:
                res.insert(0, (code, name))
            elif digits in code:
                res.append((code, name))
    else:       # 按中文名模糊
        ql = q.lower()
        starts, contains = [], []
        for code, name in lst:
            nl = name.lower()
            if nl.startswith(ql):
                starts.append((code, name))
            elif ql in nl:
                contains.append((code, name))
        res = starts + contains

    # 去重保序
    out, seen = [], set()
    for c, n in res:
        if c not in seen:
            out.append((c, n))
            seen.add(c)
    return out[:limit]


if __name__ == "__main__":
    print("US 'apple':", search_us("apple")[:3])
    print("US 'NVDA':", search_us("NVDA")[:2])
    print("A '茅台':", search_ashare("茅台")[:3])
    print("A '600519':", search_ashare("600519")[:2])
