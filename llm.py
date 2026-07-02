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
def _clean_journal(txt: str, strip_numbers: bool = False) -> str:
    """后处理: 剥掉模型硬塞的表格/标题/项目符号, 只留散文, 规整结尾免责声明。
    strip_numbers=True 时进一步删除所有数字(连同紧邻单位), 杜绝大模型臆造的错误数值。"""
    import re
    keep = []
    for ln in (txt or "").splitlines():
        s = ln.strip()
        if not s or "|" in s:
            continue
        if s.startswith(("#", ">", "---", "***", "===", "```")):
            continue
        s = re.sub(r"^[-*•·]+\s*", "", s)
        s = re.sub(r"^\d+\s*[\.、)]\s*", "", s)
        s = s.replace("**", "").replace("__", "").replace("`", "").replace("#", "")
        keep.append(s)
    out = "".join(keep).strip()
    if strip_numbers:
        # 删除 "1.5万美元 / 25% / 81.6分 / 1.28x / 92-97" 这类数值(含紧邻单位)
        out = re.sub(r"[\dＯo]+[\d,.\-~／/]*\s*(万美元|亿美元|美元|万股|万|亿|％|%|分|倍|[xX]|美金)?", "", out)
        out = re.sub(r"[（(【\[]\s*[）)】\]]", "", out)      # 清掉被掏空的括号
        out = re.sub(r"[，、；：,;:]{2,}", "，", out)          # 合并重复标点
        out = re.sub(r"\s{2,}", " ", out).strip()
    out = out.replace("仅供研究，非投资建议。", "").replace("仅供研究，非投资建议", "").strip()
    if out:
        out += "\n\n仅供研究，非投资建议。"
    return out


def llm_journal(trades: list[dict], summ: dict, regime: str = "",
                factors_brief: str = "", creds: dict | None = None,
                timeout: int = 30) -> str:
    creds = creds or get_credentials()
    if not creds.get("api_key"):
        return rule_based_journal(trades, summ, regime)
    try:
        import requests

        def _strip_num(s: str) -> str:
            import re as _re
            return _re.sub(r"[\d]+[\d,.\-~／/]*\s*(万美元|亿美元|美元|万|亿|％|%|分|倍|[xX])?", "", str(s)).strip("，、；：,;: （）()【】")

        buys = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]
        # 只给定性锚点, 不给任何价格/市值/评分数字, 避免大模型误读乱算
        facts = []
        if regime:
            facts.append(f"大盘环境为{regime}")
        if buys:
            facts.append("顺势建仓或加仓" + "、".join(
                f"{t.get('name','') or t['code']}" for t in buys)
                + "，理由是" + "；".join(dict.fromkeys(_strip_num(t['reason']) for t in buys)))
        if sells:
            facts.append("减仓或清仓" + "、".join(
                f"{t.get('name','') or t['code']}" for t in sells)
                + "，理由是" + "；".join(dict.fromkeys(_strip_num(t['reason']) for t in sells)))
        if not trades:
            facts.append("今日信号未触发调仓，维持原持仓观望")
        if factors_brief:
            facts.append(f"因子概览为{_strip_num(factors_brief)}")
        # 仓位/现金/盈亏 转成定性描述
        try:
            cash_ratio = float(summ["cash"]) / max(float(summ["total"]), 1e-9)
        except Exception:
            cash_ratio = 0.5
        pos_desc = ("现金充裕、仓位偏轻" if cash_ratio > 0.5 else
                    "仓位适中、尚有余力" if cash_ratio > 0.2 else "现金较少、仓位偏重")
        ret = float(summ.get("ret_pct", 0))
        ret_desc = "略有浮盈" if ret > 0.5 else "小幅浮亏" if ret < -0.5 else "基本持平"
        facts.append(f"当前账户{pos_desc}，开仓以来{ret_desc}")
        facts_txt = "；".join(facts)

        sys_msg = (
            "你是一位量化基金操盘手，为自己的模拟盘写每日操盘手记。"
            "把用户给的『今日交易要点』改写成一段自然流畅的中文散文。硬性规则："
            "输出必须是纯散文，一个自然段，100~160字；"
            "绝对不要出现任何数字、百分比、价格、表格、竖线、井号、连字符列表或分点编号；"
            "不得新增要点里没有的概念(杠杆/保证金/贝塔/夏普/目标价等)；"
            "语气专业克制、第一人称手记感；只谈今天为何这样调仓、组合当前偏进攻还是偏防守、"
            "下一步关注什么；最后另起一行写：仅供研究，非投资建议。")
        eg_user = ("今日交易要点：大盘环境为Risk-On进攻；顺势建仓或加仓苹果、谷歌，"
                   "理由是趋势走强、资金流入；当前账户现金充裕、仓位偏轻，开仓以来基本持平。"
                   "请改写成操盘手记散文。")
        eg_assistant = ("今日大盘处于Risk-On进攻区间，系统对偏多信号更友好，我顺势对趋势走强、"
                        "资金持续流入的苹果与谷歌各建了一笔仓位，属于典型的顺势加仓。目前组合仅"
                        "两只科技龙头、仓位偏轻、现金充裕，整体偏温和进攻，尚有较大加仓与回旋空间。"
                        "下一步我会盯住它们能否放量站稳，以及大盘是否维持Risk-On，一旦转弱便先收缩仓位。\n"
                        "仅供研究，非投资建议。")
        user_msg = f"今日交易要点：{facts_txt}。请改写成操盘手记散文。"
        r = requests.post(
            f"{creds['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {creds['api_key']}",
                     "Content-Type": "application/json"},
            json={"model": creds["model"],
                  "messages": [{"role": "system", "content": sys_msg},
                               {"role": "user", "content": eg_user},
                               {"role": "assistant", "content": eg_assistant},
                               {"role": "user", "content": user_msg}],
                  "temperature": 0.4, "max_tokens": 320},
            timeout=timeout)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        cleaned = _clean_journal(raw, strip_numbers=True)
        body = cleaned.replace("仅供研究，非投资建议。", "").strip()
        # 大模型偶尔仍会跑偏(过短/残留表格/大段罗列), 兜底回退到准确的规则版
        if len(body) < 40 or "|" in raw or body.count("：") > 4:
            return rule_based_journal(trades, summ, regime)
        return cleaned
    except Exception as e:
        return rule_based_journal(trades, summ, regime) + f"\n\n_(大模型调用失败，已用规则版：{e})_"


# ---------------------------------------------------------------- 个股 AI 点评
def _signal_word(score: float) -> str:
    s = float(score or 0)
    if s >= 70:
        return "多因子共振、明显看多"
    if s >= 58:
        return "整体偏多、可逢低介入"
    if s >= 45:
        return "多空均衡、宜观望"
    if s >= 35:
        return "偏空、宜谨慎"
    return "明显偏空、倾向回避"


def _pos_neg_factors(factors: dict) -> tuple[list[str], list[str]]:
    pos, neg = [], []
    for name, val in (factors or {}).items():
        try:
            v = float(val)
        except Exception:
            continue
        if v >= 65:
            pos.append(str(name))
        elif v <= 38:
            neg.append(str(name))
    return pos[:4], neg[:4]


def rule_based_review(code: str, name: str, score: float, action: str,
                      factors: dict, tech: list[str] | None = None,
                      regime: str = "", earnings_soon: bool = False) -> str:
    pos, neg = _pos_neg_factors(factors)
    parts = [f"{name or code} 当前{_signal_word(score)}，量化信号为「{action}」。"]
    if pos:
        parts.append("主要支撑来自" + "、".join(pos) + "等因子偏强。")
    if neg:
        parts.append("需警惕" + "、".join(neg) + "等因子偏弱。")
    if tech:
        import re as _re
        t0 = _re.sub(r"\s*[\d.]+\s*", "", tech[0]).strip("，。 ")
        if t0:
            parts.append(t0 + "。")
    if regime:
        parts.append(f"当前大盘环境为{regime}，顺势时系统更友好。")
    if earnings_soon:
        parts.append("临近财报，波动或加大，可等财报落地再决策。")
    parts.append("具体买卖点与仓位请结合上方的评分、止损目标价与自身风险承受能力。")
    return "".join(parts) + "\n\n仅供研究，非投资建议。"


def llm_stock_review(code: str, name: str, score: float, action: str,
                     factors: dict, tech: list[str] | None = None,
                     regime: str = "", earnings_soon: bool = False,
                     creds: dict | None = None, timeout: int = 30) -> str:
    """搜索个股时的『AI 研究员点评』。只喂定性锚点, 去数字, 失败/跑偏回退规则版。"""
    creds = creds or get_credentials()
    if not creds.get("api_key"):
        return rule_based_review(code, name, score, action, factors,
                                 tech, regime, earnings_soon)
    try:
        import re
        import requests
        # 只喂"综合立场+趋势姿态+大盘+财报", 不喂任何因子强弱(DeepSeek 会强行加"然而"唱反调把结论翻转);
        # 精确的因子归因与强弱在上方确定性的"策略解读"面板已给出。
        stance = _signal_word(score)
        facts = [f"这只股票是{name or code}，量化综合结论是{stance}，操作信号为{action}"]
        if tech:
            posture = ""
            for x in tech:
                if any(k in x for k in ("均线", "趋势", "排列", "通道")):
                    posture = re.sub(r"[\d./]+", "", x).strip("。 ")
                    break
            if posture:
                facts.append("技术形态方面" + posture)
        if regime:
            facts.append(f"当前大盘环境为{regime}")
        if earnings_soon:
            facts.append("该股临近财报，事件不确定性较高")
        facts_txt = "；".join(facts)

        sys_msg = (
            "你是一位专业、克制的量化研究员，为用户搜索的这只股票写一段『研究点评』。"
            "把用户给的要点改写成一段自然流畅的中文散文。硬性规则："
            "输出必须是纯散文，一到两个自然段，130~200字；"
            "绝对不要出现任何数字、百分比、价格、表格、竖线、井号、连字符列表或分点编号；"
            "不得新增要点里没有的概念(具体因子、超买超卖、顶背离、目标价、点位等)；"
            "最重要：必须与要点给出的『量化综合结论』方向完全一致——结论偏多就通篇偏多，"
            "结论偏空就通篇偏空，严禁用『然而/但』把结论反转成相反方向；"
            "语气专业中立、像卖方研究员口吻；讲清：当前是什么格局、该用什么思路参与、"
            "结合大盘环境要注意什么、需要盯住哪些变化；"
            "最后另起一行写：仅供研究，非投资建议。")
        eg_user = ("要点：这只股票是英伟达，量化综合结论是整体偏多、可逢低介入，操作信号为买入；"
                   "技术形态方面价格站上主要均线、多头排列；当前大盘环境为Risk-On进攻。"
                   "请写成研究点评散文。")
        eg_assistant = ("英伟达当前维持偏多格局，量化综合结论倾向逢低介入，价格稳居主要均线上方并呈多头排列，"
                        "中期方向仍偏强，市场愿意给予其成长溢价。参与思路上宜顺势而为，逢回调分批布局、"
                        "严格控制单票仓位，而非在情绪亢奋时追高。考虑到当前处于Risk-On进攻区间，"
                        "系统对偏多信号更为友好，外部环境亦提供支撑。后续需盯住多头结构能否延续、"
                        "以及大盘风险偏好是否维持，一旦环境转弱便应及时收缩仓位、落袋为安。\n"
                        "仅供研究，非投资建议。")
        user_msg = f"要点：{facts_txt}。请写成研究点评散文。"
        r = requests.post(
            f"{creds['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {creds['api_key']}",
                     "Content-Type": "application/json"},
            json={"model": creds["model"],
                  "messages": [{"role": "system", "content": sys_msg},
                               {"role": "user", "content": eg_user},
                               {"role": "assistant", "content": eg_assistant},
                               {"role": "user", "content": user_msg}],
                  "temperature": 0.35, "max_tokens": 420},
            timeout=timeout)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        cleaned = _clean_journal(raw, strip_numbers=True)
        body = cleaned.replace("仅供研究，非投资建议。", "").strip()
        if len(body) < 50 or "|" in raw or body.count("：") > 4:
            return rule_based_review(code, name, score, action, factors,
                                     tech, regime, earnings_soon)
        return cleaned
    except Exception as e:
        return rule_based_review(code, name, score, action, factors,
                                 tech, regime, earnings_soon) \
            + f"\n\n_(大模型调用失败，已用规则版：{e})_"
