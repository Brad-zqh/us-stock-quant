"""可选的 LLM 操盘手解说 (llm.py)
================================
把每日调仓 + 因子情况, 让大模型写成"真人操盘手日志"。

- 不填 API Key → 自动用免费规则版 (rule_based_journal), 绝不报错。
- 填了 OpenAI 兼容的 Key → 用大模型生成自然语言 (OpenAI / DeepSeek / Kimi / 通义 均可)。

凭证来源优先级: 传入参数 > 环境变量 > config.json。
环境变量: LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
"""
from __future__ import annotations

import os
import json

_CFG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# 常见服务的默认 base_url / 模型 (便于用户只填 key)
PROVIDERS = {
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "openai":   ("https://api.openai.com/v1", "gpt-4o-mini"),
    "kimi":     ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "qwen":     ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
}


def _load_cfg() -> dict:
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("llm", {}) or {}
    except Exception:
        return {}


def get_credentials(api_key=None, base_url=None, model=None, provider=None) -> dict:
    cfg = _load_cfg()
    provider = (provider or os.getenv("LLM_PROVIDER") or cfg.get("provider") or "").lower()
    p_base, p_model = PROVIDERS.get(provider, ("", ""))
    return {
        "api_key": api_key or os.getenv("LLM_API_KEY") or cfg.get("api_key") or "",
        "base_url": base_url or os.getenv("LLM_BASE_URL") or cfg.get("base_url") or p_base
                    or "https://api.openai.com/v1",
        "model": model or os.getenv("LLM_MODEL") or cfg.get("model") or p_model or "gpt-4o-mini",
    }


def has_llm(api_key=None, **kw) -> bool:
    return bool(get_credentials(api_key=api_key, **kw)["api_key"])


# ---------------------------------------------------------------- 免费规则版
def rule_based_journal(trades: list[dict], summ: dict, regime: str = "") -> str:
    lines = []
    if regime:
        lines.append(f"**大盘环境**：{regime}。")
    if not trades:
        lines.append("今日信号未触发调仓，维持原持仓观望。")
    else:
        buys = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]
        if buys:
            lines.append("**加/建仓**：" + "；".join(
                f"{t['code']} {t.get('name','')} 买入 ${t['amount']:,.0f}（{t['reason']}）"
                for t in buys))
        if sells:
            lines.append("**减/清仓**：" + "；".join(
                f"{t['code']} {t.get('name','')} 卖出 ${t['amount']:,.0f}"
                + (f"，实现盈亏 ${t['pnl']:,.0f}" if t.get('pnl') else "")
                + f"（{t['reason']}）" for t in sells))
    lines.append(
        f"**账户**：总资产 ${summ['total']:,.0f}（累计 {summ['ret_pct']:+.1f}%），"
        f"现金 ${summ['cash']:,.0f}，持仓 {summ['n_pos']} 只。")
    lines.append("_以上为规则引擎自动生成，仅供研究，非投资建议。_")
    return "\n\n".join(lines)


# ---------------------------------------------------------------- 大模型版
def llm_journal(trades: list[dict], summ: dict, regime: str = "",
                factors_brief: str = "", creds: dict | None = None,
                timeout: int = 30) -> str:
    creds = creds or get_credentials()
    if not creds.get("api_key"):
        return rule_based_journal(trades, summ, regime)
    try:
        import requests
        trade_txt = "\n".join(
            f"- {t['side']} {t['code']} {t.get('name','')} ${t['amount']:,.0f} "
            f"@{t['price']} 理由:{t['reason']}" for t in trades) or "（今日无调仓）"
        pos_txt = "\n".join(
            f"- {r['代码']} {r['名称']} 市值${r['市值']:,.0f} 盈亏{r['盈亏%']:+.1f}%"
            for r in summ.get("rows", [])[:10]) or "（空仓）"
        prompt = (
            "你是一位专业、克制的量化基金操盘手。基于以下今日模拟盘调仓与持仓，"
            "用中文写一段 150 字以内的『操盘日志』：说明今天为什么这样买卖、"
            "组合当前的风险偏好、以及下一步关注点。语气专业、不夸大、不做收益承诺，"
            "结尾注明『仅供研究，非投资建议』。\n\n"
            f"【大盘环境】{regime}\n【今日调仓】\n{trade_txt}\n"
            f"【当前持仓】\n{pos_txt}\n【因子概览】{factors_brief}\n"
            f"【账户】总资产${summ['total']:,.0f} 累计{summ['ret_pct']:+.1f}% "
            f"现金${summ['cash']:,.0f}")
        r = requests.post(
            f"{creds['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {creds['api_key']}",
                     "Content-Type": "application/json"},
            json={"model": creds["model"],
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.6, "max_tokens": 400},
            timeout=timeout)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"].strip()
        return txt or rule_based_journal(trades, summ, regime)
    except Exception as e:
        return rule_based_journal(trades, summ, regime) + f"\n\n_(大模型调用失败，已用规则版：{e})_"
