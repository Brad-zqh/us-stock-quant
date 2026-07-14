"""
推送模块 (notify.py)
===================
生成每日信号报告, 支持:
  1. 邮件 (SMTP)        —— 需要邮箱授权码
  2. 微信 (Server酱 SCT) —— 需要 SendKey, 见 https://sct.ftqq.com

为安全起见, 凭证从环境变量或 config.json 读取, 不写死在代码里。

config.json 示例:
{
  "email": {
    "smtp": "smtp.zju.edu.cn", "port": 465,
    "user": "zhaoqiuhao@zju.edu.cn", "password": "邮箱授权码",
    "to": "zhaoqiuhao@zju.edu.cn"
  },
  "serverchan_key": "你的SCTxxxx的SendKey"
}
"""
from __future__ import annotations
import json
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header
from pathlib import Path

import engine

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


# ----------------------------------------------------------------------------
# 报告生成
# ----------------------------------------------------------------------------
def build_report(res: dict, top_news: int = 2) -> tuple[str, str]:
    """返回 (纯文本, Markdown)。"""
    t = res["table"]
    lines_txt = [f"📈 美股量化信号  {res['asof']}", ""]
    lines_md = [f"## 📈 美股量化信号  \n更新: {res['asof']}\n",
                "| 代码 | 综合分 | 信号 | 现价 | 止损 | 目标 | 仓位 |",
                "|---|---|---|---|---|---|---|"]
    for _, r in t.iterrows():
        lines_txt.append(
            f"{r['代码']:<5} {r['综合分']:>5}  {r['信号']:<12} "
            f"现价{r['现价']} 止损{r['止损价']} 目标{r['目标价']} 仓位{r['建议仓位%']}%")
        lines_md.append(
            f"| **{r['代码']}** | {r['综合分']} | {r['信号']} | {r['现价']} | "
            f"{r['止损价']} | {r['目标价']} | {r['建议仓位%']}% |")

    # 财报临近提醒
    warns = []
    for code, det in res.get("detail", {}).items():
        e = det.get("earnings")
        if e and e.get("soon"):
            warns.append(f"{code} {e['days']}天后({e['date']})财报")
    if warns:
        lines_txt += ["", "⚠️ 财报临近(谨慎追高): " + "; ".join(warns)]
        lines_md += ["\n### ⚠️ 财报临近 (谨慎追高)", *[f"- {w}" for w in warns]]

    # 重点票的新闻
    buys = t[t["综合分"] >= 58]
    if len(buys):
        lines_txt += ["", "── 重点关注新闻 ──"]
        lines_md += ["\n### 📰 重点票新闻"]
        for code in buys["代码"]:
            items = res["detail"][code]["news"][:top_news]
            for it in items:
                tag = "🟢" if it["sentiment"] > 0.1 else ("🔴" if it["sentiment"] < -0.1 else "⚪")
                lines_txt.append(f"{code} {tag} {it['title'][:60]}")
                lines_md.append(f"- {code} {tag} {it['title']}")

    lines_txt.append("\n⚠️ 仅供研究, 非投资建议。")
    lines_md.append("\n> ⚠️ 仅供研究, 非投资建议。")
    return "\n".join(lines_txt), "\n".join(lines_md)


# ----------------------------------------------------------------------------
# 邮件
# ----------------------------------------------------------------------------
def send_email(subject: str, body: str, cfg: dict | None = None) -> str:
    cfg = cfg or load_config().get("email", {})
    required = ("smtp", "user", "password", "to")
    if not all(cfg.get(k) for k in required):
        return "❌ 邮件未配置 (需 smtp/user/password/to)"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]
    port = int(cfg.get("port", 465))
    try:
        ctx = ssl.create_default_context()
        if port in (465, 994):
            with smtplib.SMTP_SSL(cfg["smtp"], port, context=ctx) as s:
                s.login(cfg["user"], cfg["password"])
                s.sendmail(cfg["user"], [cfg["to"]], msg.as_string())
        else:
            with smtplib.SMTP(cfg["smtp"], port) as s:
                s.starttls(context=ctx)
                s.login(cfg["user"], cfg["password"])
                s.sendmail(cfg["user"], [cfg["to"]], msg.as_string())
        return f"✅ 邮件已发送至 {cfg['to']}"
    except Exception as e:
        return f"❌ 邮件发送失败: {e}"


# ----------------------------------------------------------------------------
# 微信 (Server酱 Turbo)
# ----------------------------------------------------------------------------
def send_wechat(title: str, md_body: str, key: str | None = None) -> str:
    key = key or load_config().get("serverchan_key", "") or os.getenv("SCT_KEY", "")
    if not key:
        return "❌ 微信未配置 (需 Server酱 SendKey)"
    import urllib.request
    import urllib.parse
    import urllib.error
    url = f"https://sctapi.ftqq.com/{key}.send"
    data = urllib.parse.urlencode({"title": title, "desp": md_body}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as r:
            resp = json.loads(r.read().decode())
        if resp.get("code") == 0:
            return "✅ 微信推送成功"
        return f"❌ 微信推送失败: {resp.get('message')}"
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode(errors="replace"))
            msg = detail.get("info") or detail.get("message") or str(e)
        except Exception:
            msg = str(e)
        return f"❌ 微信推送失败: {msg}"
    except Exception as e:
        return f"❌ 微信推送失败: {e}"


def run_and_push(watchlist=None, period="2y", email=True, wechat=True) -> dict:
    """跑一次分析并按配置推送。供命令行/定时任务调用。"""
    wl = watchlist or engine.DEFAULT_WATCHLIST
    res = engine.analyze(wl, period=period, use_earnings=True)
    txt, md = build_report(res)
    out = {"report_txt": txt, "report_md": md}
    subj = f"美股量化信号 {res['asof'][:10]}"
    if email:
        out["email"] = send_email(subj, txt)
    if wechat:
        out["wechat"] = send_wechat(subj, md)
    return out


if __name__ == "__main__":
    r = run_and_push(email=False, wechat=False)   # 默认仅打印, 不实际发送
    print(r["report_txt"])
