#!/usr/bin/env python3
"""皓量化账户桌面看板 (HTML 版)。

生成本地 HTML 页面, 汇总:
  - A股本地虚拟盘
  - 美股富途模拟盘
  - 美股富途实盘

只读查看, 不下单。
"""
from __future__ import annotations

import html
import json
import logging
import os
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "account_dashboard.html")
logging.disable(logging.WARNING)


def _fmt_money(x, cur="$") -> str:
    try:
        return f"{cur}{float(x):,.2f}"
    except Exception:
        return f"{cur}0.00"


def _fmt_num(x, nd=4) -> str:
    try:
        return f"{float(x):,.{nd}f}"
    except Exception:
        return "0"


def _fmt_pct(x) -> str:
    try:
        return f"{float(x):+.2f}%"
    except Exception:
        return "+0.00%"


def _money_class_text(value: float, cur: str = "$") -> str:
    return _fmt_money(value, cur)


def _float_or_zero(x) -> float:
    try:
        if x is None:
            return 0.0
        s = str(x).strip()
        if s.upper() in ("", "N/A", "NA", "NAN", "NONE", "--"):
            return 0.0
        return float(x)
    except Exception:
        return 0.0


def _h(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _paper_cn() -> dict:
    path = os.path.join(HERE, "state", "paper_account_cn.json")
    acc = _read_json(path)
    cash = float(acc.get("cash", 0) or 0)
    start_cash = float(acc.get("start_cash", cash) or cash or 0)
    positions = acc.get("positions", {}) or {}
    rows = []
    invested = 0.0
    for code, p in positions.items():
        shares = float(p.get("shares", 0) or 0)
        avg = float(p.get("avg_cost", 0) or 0)
        price = avg
        market_val = shares * price
        invested += market_val
        rows.append({
            "code": code,
            "name": p.get("name", ""),
            "qty": shares,
            "cost": avg,
            "price": price,
            "market_val": market_val,
            "pl": 0.0,
            "pl_ratio": 0.0,
        })
    total = cash + invested
    total_pl = total - start_cash if start_cash else 0
    ret = (total / start_cash - 1) * 100 if start_cash else 0
    return {
        "ok": True,
        "title": "A股本地虚拟盘",
        "subtitle": "本地 JSON · 不向券商下单 · 快速模式按成本估值",
        "cur": "¥",
        "summary": {
            "总资产": _fmt_money(total, "¥"),
            "现金": _fmt_money(cash, "¥"),
            "持仓市值": _fmt_money(invested, "¥"),
            "账户总盈亏": _money_class_text(total_pl, "¥"),
            "账户收益率": _fmt_pct(ret),
            "成交": f"{len(acc.get('trades', []) or [])} 笔",
        },
        "rows": rows,
    }


def _futu_account(env_name: str) -> dict:
    try:
        from futu import OpenSecTradeContext, RET_OK, SecurityFirm, TrdEnv, TrdMarket
    except Exception as e:
        return {"ok": False, "title": env_name, "error": f"futu-api 不可用: {e!r}", "rows": []}

    host = os.getenv("FUTU_HOST", "127.0.0.1")
    port = int(os.getenv("FUTU_PORT", "11111"))
    env = TrdEnv.SIMULATE if env_name == "美股富途模拟盘" else TrdEnv.REAL
    ctx = None
    try:
        ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=host,
            port=port,
            security_firm=SecurityFirm.FUTUSECURITIES,
        )
        ret, acc = ctx.accinfo_query(trd_env=env, currency="USD")
        if ret != RET_OK:
            return {"ok": False, "title": env_name, "error": f"查询资金失败: {acc}", "rows": []}
        a = acc.iloc[0]
        total = float(a.get("total_assets", 0) or 0)
        cash = float(a.get("us_cash", a.get("cash", 0)) or 0)
        market_val = float(a.get("market_val", 0) or 0)
        upl = _float_or_zero(a.get("unrealized_pl", 0))

        ret, pos = ctx.position_list_query(trd_env=env)
        if ret != RET_OK:
            return {"ok": False, "title": env_name, "error": f"查询持仓失败: {pos}", "rows": []}

        rows = []
        for _, r in pos.iterrows():
            qty = float(r.get("qty", 0) or 0)
            if qty == 0:
                continue
            code = str(r.get("code", "") or "")
            if "." in code:
                code = code.split(".", 1)[1]
            rows.append({
                "code": code,
                "name": str(r.get("stock_name", "") or ""),
                "qty": qty,
                "cost": _float_or_zero(r.get("cost_price", 0)),
                "price": _float_or_zero(r.get("nominal_price", 0)),
                "market_val": _float_or_zero(r.get("market_val", 0)),
                "pl": _float_or_zero(r.get("pl_val", 0)),
                "pl_ratio": _float_or_zero(r.get("pl_ratio", 0)),
            })
        rows.sort(key=lambda x: abs(x["market_val"]), reverse=True)
        pos_pl = sum(r["pl"] for r in rows)
        cost_basis = sum((r["qty"] * r["cost"]) for r in rows)
        pos_pl_ratio = (pos_pl / cost_basis * 100) if cost_basis else 0.0
        total_pl_est = total - (cash + cost_basis)
        subtitle = "SIMULATE · 假钱真流程" if env == TrdEnv.SIMULATE else "REAL · 真金账户"
        summary = {
            "总资产": _fmt_money(total),
            "现金": _fmt_money(cash),
            "持仓市值": _fmt_money(market_val),
            "持仓盈亏": _money_class_text(pos_pl, "$"),
            "持仓盈亏率": _fmt_pct(pos_pl_ratio),
            "总盈亏估算": _money_class_text(total_pl_est, "$"),
            "持仓": f"{len(rows)} 只",
        }
        return {
            "ok": True,
            "title": env_name,
            "subtitle": f"{subtitle} · 网关 {host}:{port}",
            "cur": "$",
            "summary": summary,
            "rows": rows,
        }
    except Exception as e:
        return {"ok": False, "title": env_name, "error": f"读取失败: {e!r}", "rows": []}
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass


def _summary_html(summary: dict) -> str:
    items = []
    for k, v in summary.items():
        cls = ""
        if "盈亏" in k or "收益" in k:
            s = str(v)
            cls = "pos" if "+" in s and not s.startswith("-") else ("neg" if "-" in s else "")
        items.append(f"<div class='metric'><span>{_h(k)}</span><strong class='{cls}'>{_h(v)}</strong></div>")
    return "<div class='metrics'>" + "".join(items) + "</div>"


def _rows_html(rows: list[dict], cur: str) -> str:
    if not rows:
        return "<div class='empty'>空仓</div>"
    trs = []
    for r in rows:
        pl = float(r.get("pl", 0) or 0)
        cls = "pos" if pl > 0 else ("neg" if pl < 0 else "")
        trs.append(
            "<tr>"
            f"<td class='code'>{_h(r.get('code'))}</td>"
            f"<td>{_h(r.get('name'))}</td>"
            f"<td class='num'>{_fmt_num(r.get('qty'), 4)}</td>"
            f"<td class='num'>{_fmt_money(r.get('cost'), cur)}</td>"
            f"<td class='num'>{_fmt_money(r.get('price'), cur)}</td>"
            f"<td class='num'>{_fmt_money(r.get('market_val'), cur)}</td>"
            f"<td class='num {cls}'>{_fmt_money(pl, cur)}</td>"
            f"<td class='num {cls}'>{_fmt_pct(r.get('pl_ratio'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>代码</th><th>名称</th><th class='num'>数量</th><th class='num'>成本</th>"
        "<th class='num'>现价</th><th class='num'>市值</th><th class='num'>盈亏</th><th class='num'>盈亏%</th>"
        "</tr></thead><tbody>"
        + "".join(trs)
        + "</tbody></table>"
    )


def _card(data: dict) -> str:
    ok = bool(data.get("ok"))
    badge = "正常" if ok else "异常"
    status = "ok" if ok else "bad"
    if not ok:
        body = f"<div class='error'>{_h(data.get('error', '读取失败'))}</div>"
    else:
        body = _summary_html(data.get("summary", {})) + _rows_html(data.get("rows", []), data.get("cur", "$"))
    return f"""
    <section class="card">
      <div class="card-head">
        <div>
          <h2>{_h(data.get('title'))}</h2>
          <p>{_h(data.get('subtitle', ''))}</p>
        </div>
        <span class="badge {status}">{badge}</span>
      </div>
      <div class="card-body">{body}</div>
    </section>
    """


def build_once() -> str:
    cards = [_card(_paper_cn()), _card(_futu_account("美股富途模拟盘")), _card(_futu_account("美股富途实盘"))]
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>皓量化账户看板</title>
  <style>
    :root {{
      color-scheme: dark;
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
      background: #111318;
      color: #e7eaf0;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 22px; overflow-x: hidden; }}
    header {{
      display: flex; align-items: baseline; justify-content: space-between;
      gap: 16px; margin-bottom: 18px;
    }}
    h1 {{ margin: 0; font-size: 24px; }}
    .meta {{ color: #9aa4b2; font-size: 14px; white-space: nowrap; }}
    .grid {{ display: flex; flex-direction: column; gap: 16px; align-items: stretch; }}
    .card {{
      background: #181b22; border: 1px solid #2a2f3a; border-radius: 8px;
      overflow: hidden; min-width: 0;
    }}
    .card-head {{
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px; padding: 12px 14px; border-bottom: 1px solid #2a2f3a; background: #20242d;
    }}
    h2 {{ margin: 0; font-size: 18px; }}
    p {{ margin: 4px 0 0; color: #9aa4b2; font-size: 12px; }}
    .badge {{ border-radius: 999px; padding: 3px 9px; font-size: 12px; white-space: nowrap; }}
    .ok {{ background: #113d25; color: #7ee0a0; }}
    .bad {{ background: #4a1d21; color: #ff9aa5; }}
    .card-body {{ padding: 14px; overflow-x: auto; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)); gap: 8px; margin-bottom: 14px; }}
    .metric {{ background: #11151c; border: 1px solid #27303c; border-radius: 6px; padding: 8px; }}
    .metric span {{ display: block; color: #8f9bad; font-size: 12px; margin-bottom: 3px; }}
    .metric strong {{ font-size: 16px; }}
    table {{ width: 100%; min-width: 980px; border-collapse: collapse; table-layout: auto; font-size: 14px; }}
    th, td {{ padding: 7px 6px; border-bottom: 1px solid #2a2f3a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    th {{ color: #9aa4b2; font-weight: 600; text-align: left; background: #151922; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .code {{ font-weight: 700; color: #dbeafe; }}
    .pos {{ color: #ff6b7a; }}
    .neg {{ color: #5bd38b; }}
    .empty, .error {{ color: #9aa4b2; padding: 24px 4px; }}
    .error {{ color: #ff9aa5; }}
    footer {{ margin-top: 14px; color: #8b95a3; font-size: 13px; }}
    @media (max-width: 1280px) {{ .metrics {{ grid-template-columns: repeat(2, minmax(150px, 1fr)); }} }}
  </style>
</head>
<body>
  <header>
    <h1>皓量化账户看板</h1>
    <div class="meta">刷新时间: {stamp} · 重新双击桌面入口可刷新</div>
  </header>
  <main class="grid">
    {''.join(cards)}
  </main>
  <footer>A股为本地虚拟盘, 不向券商下单；美股为富途 OpenD 只读账户查询。</footer>
</body>
</html>
"""


def write_page() -> None:
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(build_once())


def main() -> int:
    write_page()
    if "--no-open" not in sys.argv:
        webbrowser.open("file:///" + OUT.replace("\\", "/"))
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
