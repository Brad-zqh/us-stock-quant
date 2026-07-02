"""
量化选股交互看板 (Streamlit)
============================
运行:  streamlit run app.py

页面:
  1. 自选股扫描排名 — 综合分 / 信号 / 风控方案 一览
  2. 个股详情 — K线+均线+MACD+RSI, 因子雷达, 回测净值
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import os

import engine
import notify
import universe
import ashare
import resolve
import funds
import explain
import paper
import llm
import auth
import userstore

st.set_page_config(page_title="皓哥量化", layout="wide", page_icon="📈")

# 多用户登录门 (未启用多用户时返回 None, 保持单用户模式; 未登录会在此停止渲染)
CURRENT_USER = auth.login_gate()

# ---------------------------------------------------------------- 侧边栏配置
st.sidebar.title("⚙️ 配置")
st.sidebar.caption("数据: yfinance 日线 · 仅供研究, 非投资建议")

# 已登录: 顶部显示用户 + 退出
if CURRENT_USER:
    _uc1, _uc2 = st.sidebar.columns([2, 1])
    _uc1.markdown(f"👤 **{CURRENT_USER}**" + ("　🛡️管理员" if auth.is_admin() else ""))
    if _uc2.button("退出", key="logout_btn"):
        auth.logout()
        st.rerun()

# 每人自选股默认值: 已登录用其账户里保存的, 否则用系统默认池
_default_pool = "\n".join(f"{k}  {v}" for k, v in engine.DEFAULT_WATCHLIST.items())
if CURRENT_USER:
    _prof = userstore.get_profile(CURRENT_USER) or {}
    _saved_wt = (_prof.get("watchlist_text") or "").strip()
    default_codes = _saved_wt if _saved_wt else _default_pool
else:
    default_codes = _default_pool
codes_text = st.sidebar.text_area(
    "自选股 (每行: 代码 空格 名称)", value=default_codes, height=200)
if CURRENT_USER:
    if st.sidebar.button("💾 保存自选股到我的账户", use_container_width=True):
        if userstore.update_profile(CURRENT_USER, watchlist_text=codes_text):
            st.sidebar.success("已保存到你的账户。")
        else:
            st.sidebar.error("保存失败, 请重试。")
period = st.sidebar.selectbox("数据周期", ["1y", "2y", "5y"], index=1)
use_news = st.sidebar.checkbox("启用新闻情绪因子 📰", value=True,
                               help="抓取个股新闻并做金融情绪分析")
use_fund = st.sidebar.checkbox("启用基本面/分析师/资金流 📊", value=True,
                               help="PEG/营收增速/华尔街评级/目标价/OBV/CMF")
refresh = st.sidebar.button("🔄 刷新分析", type="primary", use_container_width=True)

# 解析自选股
# 常见"名字/别名 -> 正确代码"映射 (避免把公司名当成代码导致取不到行情被丢弃)
_TICKER_ALIAS = {
    "SPACEX": "SPCX", "STARLINK": "SPCX", "星舰": "SPCX", "星链": "SPCX",
    "马斯克": "SPCX", "SPACE-X": "SPCX", "SPACEX星舰": "SPCX",
}
watchlist = {}
for line in codes_text.strip().splitlines():
    parts = line.strip().split(None, 1)
    if parts:
        raw = parts[0]
        code = _TICKER_ALIAS.get(raw.upper(), raw.upper())
        name = parts[1] if len(parts) > 1 else (raw if code == raw.upper() else raw)
        watchlist[code] = name


@st.cache_data(ttl=900, show_spinner="📡 拉取行情并计算中…")
def load(wl: dict, period: str, use_news: bool, use_fund: bool):
    return engine.analyze(wl, period=period, use_news=use_news,
                          use_fundamentals=use_fund, use_earnings=True)


@st.cache_data(ttl=1800, show_spinner="🔭 扫描美股股票池中…")
def load_screen(market: str, exclude: tuple, period: str, use_fund: bool, top: int,
                themes: tuple = ()):
    pool_full = universe.US_SECTORS if market == "非科技" else universe.TECH_UNIVERSE
    pool = {k: v for k, v in pool_full.items() if (not themes or k in themes)}
    return universe.screen(exclude=set(exclude), period=period,
                           use_news=False, use_fundamentals=use_fund, top=top, pool=pool)


@st.cache_data(ttl=900, show_spinner="🇨🇳 AI 交易员拉取A股行情中…")
def load_ai_cn(period: str):
    """AI 交易员 A股龙头池独立分析 (与侧边栏美股分析互不影响)。"""
    return engine.analyze(engine.A_SHARE_WATCHLIST, period=period,
                          use_news=False, use_fundamentals=True, use_earnings=False,
                          benchmark=engine.A_BENCHMARK, bench_label="沪深300")


@st.cache_data(ttl=1800, show_spinner="🇨🇳 扫描A股龙头中…")
def ashare_screen_cached(period: str, use_fund: bool, top: int, use_news: bool,
                         themes: tuple = ()):
    return ashare.screen(period=period, use_fundamentals=use_fund,
                         top=top, use_news=use_news, themes=themes)


@st.cache_data(ttl=1800, show_spinner="💹 扫描指数基金中…")
def load_fund_screen(market: str, period: str, use_fund: bool, top: int, themes: tuple = ()):
    pool_full = funds.US_INDEX if market == "US" else funds.CN_INDEX
    pool = {k: v for k, v in pool_full.items() if (not themes or k in themes)}
    return universe.screen(exclude=set(), period=period, use_news=False,
                           use_fundamentals=use_fund, top=top, pool=pool)


@st.cache_data(ttl=3600, show_spinner=False)
def search_fund_cached(q: str, market: str):
    return funds.search_fund(q, market)


@st.cache_data(ttl=900, show_spinner="🔎 分析该股票中…")
def analyze_single(code: str, name: str, period: str, use_news: bool, use_fund: bool):
    """按单只股票代码跑完整分析, 返回 detail 字典 (供搜索个股详情用)。"""
    try:
        res = engine.analyze({code: name}, period=period, use_news=use_news,
                             use_fundamentals=use_fund, use_earnings=True)
        return res["detail"].get(code)
    except Exception as e:
        return {"__error__": str(e)}


@st.cache_data(ttl=3600, show_spinner=False)
def search_us_cached(q: str):
    return resolve.search_us(q)


@st.cache_data(ttl=3600, show_spinner="🔎 匹配A股名称中…")
def search_a_cached(q: str):
    return resolve.search_ashare(q)


def _llm_creds_from_ui():
    """统一获取大模型凭证: Streamlit Secrets(LLM_API_KEY/LLM_PROVIDER) 优先, 再退 env/config。"""
    try:
        key = st.secrets.get("LLM_API_KEY", "")
        prov = st.secrets.get("LLM_PROVIDER", "deepseek")
    except Exception:
        key, prov = "", "deepseek"
    key = key or st.session_state.get("llm_key", "")
    prov = st.session_state.get("llm_prov", prov) or prov
    if key:
        return llm.get_credentials(api_key=key, provider=prov)
    c = llm.get_credentials()
    return c if c.get("api_key") else None


if refresh:
    load.clear()
    load_screen.clear()
    ashare_screen_cached.clear()
    load_fund_screen.clear()
    analyze_single.clear()
    search_us_cached.clear()
    search_a_cached.clear()
    search_fund_cached.clear()

res = load(watchlist, period, use_news, use_fund)
table, detail = res["table"], res["detail"]

st.title("📈 皓哥量化")

# 提示: 有哪些自选股代码取不到行情被跳过 (未上市/代码错误/退市)
_missing = [f"{c}" + (f"({watchlist[c]})" if watchlist.get(c) and watchlist[c] != c else "")
            for c in watchlist if c not in detail]
if _missing:
    st.warning("⚠️ 以下自选股取不到行情已跳过(可能未上市/代码写错/已退市): "
               + "、".join(_missing)
               + "。改成正确的**交易代码**即可,如 SpaceX→`SPCX`。")

# ---------------------------------------------------------------- 顶部下载 App 入口
_DL_PAGE = "https://brad-zqh.github.io/us-stock-quant/download.html"
_REL = "https://github.com/Brad-zqh/us-stock-quant/releases/latest/download"
_pill = ("text-decoration:none;padding:3px 10px;border-radius:999px;"
         "border:1px solid #2f3640;background:#161b22;color:#e6e6e6;"
         "font-size:0.85em;white-space:nowrap")
st.markdown(
    "<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:-6px 0 10px'>"
    "<span style='color:#9aa0aa;font-size:0.85em'>📲 下载 App:</span>"
    f"<a target='_blank' rel='noopener' style='{_pill}' href='{_REL}/StockQuant-Windows-Setup.exe'>🪟 Windows</a>"
    f"<a target='_blank' rel='noopener' style='{_pill}' href='{_REL}/StockQuant-macOS.dmg'>🍎 macOS</a>"
    f"<a target='_blank' rel='noopener' style='{_pill}' href='{_REL}/StockQuant-Android.apk'>🤖 Android</a>"
    f"<a target='_blank' rel='noopener' style='{_pill};background:#ef5350;border-color:#ef5350;color:#fff' href='{_DL_PAGE}'>📥 全部下载 / iPhone</a>"
    "</div>", unsafe_allow_html=True)

reg = res.get("regime", {})
if reg:
    rc = {"🟢": "#16a34a", "🟡": "#f59e0b", "🔴": "#dc2626"}.get(reg["label"][:1], "#888")
    st.markdown(
        f"<div style='border-radius:8px;padding:8px 14px;background:#1e1e1e;"
        f"border-left:6px solid {rc};margin-bottom:6px'>"
        f"<b>🌐 大盘环境: {reg['label']}</b>　(择时分 {reg['score']})　"
        f"<span style='color:#999;font-size:0.9em'>{reg['detail']} — "
        f"Risk-On时全局略加分, Risk-Off时略减分</span></div>", unsafe_allow_html=True)
st.caption(f"更新时间: {res['asof']}　·　基准: {engine.BENCHMARK}　·　11因子加权 · "
           "🔴红=看多 🟢绿=看空")

# ---------------------------------------------------------------- 侧边栏: 推送
st.sidebar.divider()
with st.sidebar.expander("📤 推送信号报告 (邮件/微信)"):
    st.caption("凭证存于 config.json, 不上传。配置见 README。")
    cfg = notify.load_config()
    email_ok = bool(cfg.get("email", {}).get("password"))
    wechat_ok = bool(cfg.get("serverchan_key"))
    st.write(f"邮件: {'✅ 已配置' if email_ok else '⚠️ 未配置'}　"
             f"微信: {'✅ 已配置' if wechat_ok else '⚠️ 未配置'}")
    cmail = st.checkbox("发邮件", value=email_ok, disabled=not email_ok)
    cwx = st.checkbox("推微信", value=wechat_ok, disabled=not wechat_ok)
    if st.button("立即推送当前信号", use_container_width=True):
        txt, md = notify.build_report(res)
        st.code(txt[:800])
        if cmail:
            st.write(notify.send_email("美股量化信号", txt))
        if cwx:
            st.write(notify.send_wechat("美股量化信号", md))

_tab_labels = ["🏆 自选股排名", "🔍 个股详情", "🧪 模拟盘", "🤖 AI 交易员", "🔭 美股科技池",
               "🇺🇸 美股其他板块", "🇨🇳 A股选股", "💹 指数基金", "📖 模型原理"]
if CURRENT_USER:
    _tab_labels.append("⚙️ 我的")
_tabs = st.tabs(_tab_labels)
tab1, tab2, tab8, tab9, tab3, tab4, tab5, tab7, tab6 = _tabs[:9]
tab_me = _tabs[9] if CURRENT_USER else None


def _render_screen(scr, currency="$"):
    """通用: 渲染一个扫描排名表 + 买入候选汇总。"""
    if scr is None or len(scr) == 0:
        st.warning("未取到数据, 请稍后刷新。")
        return
    cols_scr = [c for c in ["代码", "名称", "主题", "综合分", "信号", "基本面", "趋势",
                            "分析师", "动量", "盈利质量", "资金流", "筹码面", "现价",
                            "止损价", "目标价", "建议仓位%"] if c in scr.columns]
    grad = [c for c in ["综合分", "基本面", "趋势", "分析师", "动量", "盈利质量",
                        "资金流", "筹码面"] if c in scr.columns]
    fmt = {c: "{:.2f}" for c in ["现价", "止损价", "目标价"] if c in scr.columns}
    fmt["建议仓位%"] = "{:.1f}"
    st.dataframe(
        scr[cols_scr].style
        .background_gradient(subset=grad, cmap="RdYlGn_r", vmin=0, vmax=100)
        .format(fmt),
        use_container_width=True, height=min(60 + 36 * len(scr), 700))
    buys = scr[scr["综合分"] >= 58]
    if len(buys):
        st.success("**🔴 买入级候选 (综合分≥58)**　" +
                   "　".join(f"{r['代码']} {r['名称']}({r['综合分']})" for _, r in buys.iterrows()))

# ================================================================ TAB 1 排名
with tab1:
    # 顶部信号卡片
    cols = st.columns(min(len(table), 7) or 1)
    for i, (_, r) in enumerate(table.iterrows()):
        with cols[i % len(cols)]:
            st.markdown(
                f"<div style='border-radius:10px;padding:10px;background:#1e1e1e;"
                f"border-left:5px solid {r['_color']}'>"
                f"<b>{r['代码']}</b><br><span style='font-size:0.8em;color:#999'>{r['名称']}</span>"
                f"<h2 style='margin:4px 0;color:{r['_color']}'>{r['综合分']}</h2>"
                f"<span style='color:{r['_color']}'>{r['信号']}</span></div>",
                unsafe_allow_html=True)

    st.markdown("###")
    factor_cols = [c for c in ["基本面", "趋势", "分析师", "动量", "盈利质量", "资金流",
                               "筹码面", "风险", "相对大盘", "新闻情绪", "强弱"]
                   if c in table.columns]
    show_cols = (["代码", "名称", "综合分", "信号"] + factor_cols +
                 ["现价", "止损价", "目标价", "止损%", "目标%", "建议仓位%"] +
                 (["距财报"] if "距财报" in table.columns else []))
    disp = table[show_cols].copy()
    st.dataframe(
        disp.style
        .background_gradient(subset=["综合分"], cmap="RdYlGn_r", vmin=0, vmax=100)
        .background_gradient(subset=factor_cols, cmap="RdYlGn_r", vmin=0, vmax=100)
        .format({"现价": "{:.2f}", "止损价": "{:.2f}", "目标价": "{:.2f}",
                 "止损%": "{:+.1f}", "目标%": "{:+.1f}", "建议仓位%": "{:.1f}"}),
        use_container_width=True, height=min(60 + 38 * len(disp), 500))

    st.info("**信号解读**　综合分≥70 强烈买入 · 58~70 买入 · 45~58 持有 · "
            "35~45 减仓 · <35 卖出。建议仓位已按波动率调整, 单票上限 25%。"
            "止损/目标价基于 ATR(2.5×/4×), 富途下单时可直接参考。")

# ================================================================ TAB 2 详情
def render_detail(code: str, info: dict, currency: str = "$", name: str = ""):
    """渲染单只股票的完整个股详情面板 (自选股选择 与 搜索 共用)。"""
    cur = currency
    d, plan, factors = info["df"], info["plan"], info["factors"]

    title = f"{code}" + (f"  {name}" if name else "")
    st.markdown(f"#### {title}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("综合分", info["score"])
    c2.metric("信号", info["action"])
    c3.metric("现价", f"{cur}{plan['现价']}")
    c4.metric("止损价", f"{cur}{plan['止损价']}", f"{plan['止损%']}%")
    c5.metric("目标价", f"{cur}{plan['目标价']}", f"{plan['目标%']}%")

    earn = info.get("earnings")
    if earn:
        if earn["soon"]:
            st.error(f"⚠️ **财报临近**: {earn['days']} 天后 ({earn['date']}) 发财报 — "
                     "财报前后波动剧烈, 谨慎追高, 可等财报落地再决策。")
        else:
            st.caption(f"📅 下次财报: {earn['date']} (还有 {earn['days']} 天)")

    # ---- 📝 策略解读 (白话归因)
    try:
        ex = explain.build_explanation(info, cur=cur, reg=res.get("regime"))
        with st.expander("📝 策略解读 — 为什么给这个信号、怎么操作", expanded=True):
            st.markdown(f"**🎯 结论**　{ex['结论']}")
            cL, cR = st.columns(2)
            with cL:
                if ex["利多"]:
                    st.markdown("**✅ 支撑看多的因素**")
                    for t in ex["利多"]:
                        st.markdown(f"- {t}")
                else:
                    st.markdown("**✅ 支撑看多的因素**\n\n- 暂无明显强项因子")
            with cR:
                if ex["利空"]:
                    st.markdown("**⚠️ 需要警惕的因素**")
                    for t in ex["利空"]:
                        st.markdown(f"- {t}")
                else:
                    st.markdown("**⚠️ 需要警惕的因素**\n\n- 暂无明显弱项因子")
            if ex["技术"]:
                st.markdown("**📈 技术位置**")
                for t in ex["技术"]:
                    st.markdown(f"- {t}")
            st.markdown(f"**🛡️ {ex['风控']}**")
            for t in ex["提示"]:
                st.markdown(f"> {t}")
            st.caption("以上为量化因子的自动归因解读, 仅供研究参考, 不构成投资建议。")
    except Exception as _e:
        st.caption(f"(策略解读生成失败: {_e})")

    # ---- 🤖 AI 研究员点评 (大模型, 按需触发以控制成本)
    with st.expander("🤖 AI 研究员点评 — 让大模型综合评述这只股票", expanded=False):
        # 就地填 Key: 本面板输入 > AI交易员页/Secrets
        try:
            _sec_k = st.secrets.get("LLM_API_KEY", "")
            _sec_p = st.secrets.get("LLM_PROVIDER", "deepseek")
        except Exception:
            _sec_k, _sec_p = "", "deepseek"
        kc1, kc2 = st.columns([3, 1])
        _provs = ["deepseek", "openai", "kimi", "qwen"]
        _pidx = _provs.index(_sec_p) if _sec_p in _provs else 0
        key_in = kc1.text_input(
            "大模型 API Key (可选)", type="password", key=f"aikey_{code}",
            value=st.session_state.get("llm_key", ""),
            placeholder="留空则用免费规则版点评",
            help="DeepSeek 最便宜: platform.deepseek.com 拿 sk-xxx。仅本次会话使用, 不保存不上传。")
        prov_in = kc2.selectbox("服务商", _provs,
                                index=_provs.index(st.session_state.get("llm_prov", _provs[_pidx]))
                                if st.session_state.get("llm_prov", _provs[_pidx]) in _provs else _pidx,
                                key=f"aiprov_{code}")
        eff_key = key_in or _sec_k
        st.session_state["llm_prov"] = prov_in
        if key_in:
            st.session_state["llm_key"] = key_in      # 同步给 AI 交易员页 & 其他面板
        _creds = llm.get_credentials(api_key=eff_key, provider=prov_in) if eff_key else None

        if _creds:
            st.caption(f"✅ 已启用大模型点评 ({_creds.get('model')})，约几分钱/次。")
        else:
            st.caption("ℹ️ 未填 Key，将使用**免费规则版**点评。填入上方 Key 即可启用大模型版。")

        rk = f"aireview_{code}"
        bc1, bc2 = st.columns([1, 2])
        gen = bc1.button("生成 AI 点评", key=f"btn_{rk}")
        auto = bc2.checkbox("自动生成 (切换到这只股票就自动出点评)",
                            key=f"auto_{rk}", value=False)
        need = gen or (auto and st.session_state.get(rk + "_for") != code)
        if need:
            try:
                ex_t = ex if isinstance(ex, dict) else {}
            except Exception:
                ex_t = {}
            _earn = info.get("earnings") or {}
            try:
                # 防 Streamlit 热重载后 llm 模块为旧缓存(缺新函数)导致 AttributeError
                if not hasattr(llm, "llm_stock_review"):
                    import importlib
                    importlib.reload(llm)
                with st.spinner("AI 正在综合评述…"):
                    st.session_state[rk] = llm.llm_stock_review(
                        code, name, info.get("score", 0), info.get("action", ""),
                        info.get("factors", {}) or {}, tech=ex_t.get("技术", []),
                        regime=(res.get("regime", {}) or {}).get("label", ""),
                        earnings_soon=bool(_earn.get("soon")), creds=_creds)
                    st.session_state[rk + "_for"] = code
            except Exception as _e:
                st.session_state[rk] = f"(AI 点评生成失败: {_e})"
                st.session_state[rk + "_for"] = code
        if st.session_state.get(rk):
            st.markdown(st.session_state[rk])
            st.caption("大模型生成，可能存在偏差，仅供研究参考，不构成投资建议。")

    # 基本面 / 分析师 / 资金流 明细
    pd_detail = info.get("plus_detail", {})
    if pd_detail:
        items = [("基本面", "📊"), ("盈利质量", "🚀"), ("分析师", "🎯"),
                 ("筹码面", "🧩"), ("资金流", "💰")]
        ccols = st.columns(len(items))
        for col, (key, icon) in zip(ccols, items):
            dd = pd_detail.get(key, {})
            if dd:
                txt = "　".join(f"{k} **{v}**" for k, v in dd.items())
                col.markdown(f"**{icon} {key}** ({info['factors'].get(key,'-')})<br>"
                             f"<span style='font-size:0.8em'>{txt}</span>",
                             unsafe_allow_html=True)

    # 原始技术指标读数 (透明化)
    last = d.iloc[-1]
    def _v(col, f="{:.1f}"):
        x = last.get(col)
        return f.format(x) if x is not None and pd.notna(x) else "—"
    st.caption(
        f"📐 技术指标　RSI {_v('RSI')}　ADX {_v('ADX')} (>25趋势强)　"
        f"KDJ-J {_v('J')}　MFI {_v('MFI')} (>80超买/<20超卖)　"
        f"CMF {_v('CMF','{:.3f}')}　布林%B {_v('BB_pctB','{:.2f}')}　"
        f"年化波动 {_v('vol_ann','{:.0%}')}")

    left, right = st.columns([3, 2])

    # ---- 左: K线 + 均线 + MACD + RSI
    with left:
        dd = d.tail(180)
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                            row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
                            subplot_titles=("K线 + 均线", "MACD", "RSI"))
        fig.add_trace(go.Candlestick(
            x=dd.index, open=dd["Open"], high=dd["High"], low=dd["Low"],
            close=dd["Close"], name="K线",
            increasing_line_color="#ef5350", decreasing_line_color="#26a69a"), row=1, col=1)
        for ma, col in [("SMA20", "#f4d35e"), ("SMA50", "#ee964b"), ("SMA200", "#9b5de5")]:
            fig.add_trace(go.Scatter(x=dd.index, y=dd[ma], name=ma,
                                     line=dict(width=1, color=col)), row=1, col=1)
        # 止损/目标参考线
        fig.add_hline(y=plan["止损价"], line=dict(color="#16a34a", dash="dot"), row=1, col=1)
        fig.add_hline(y=plan["目标价"], line=dict(color="#dc2626", dash="dot"), row=1, col=1)

        fig.add_trace(go.Bar(x=dd.index, y=dd["MACD_hist"], name="MACD柱",
                             marker_color=np.where(dd["MACD_hist"] >= 0, "#ef5350", "#26a69a")), row=2, col=1)
        fig.add_trace(go.Scatter(x=dd.index, y=dd["MACD"], name="MACD", line=dict(color="#42a5f5", width=1)), row=2, col=1)
        fig.add_trace(go.Scatter(x=dd.index, y=dd["MACD_signal"], name="Signal", line=dict(color="#ffa726", width=1)), row=2, col=1)

        fig.add_trace(go.Scatter(x=dd.index, y=dd["RSI"], name="RSI", line=dict(color="#ab47bc", width=1.2)), row=3, col=1)
        fig.add_hline(y=70, line=dict(color="#ef5350", dash="dash"), row=3, col=1)
        fig.add_hline(y=30, line=dict(color="#26a69a", dash="dash"), row=3, col=1)

        fig.update_layout(height=620, template="plotly_dark", showlegend=True,
                          xaxis_rangeslider_visible=False, margin=dict(t=40, b=10),
                          legend=dict(orientation="h", y=1.04))
        st.plotly_chart(fig, use_container_width=True)

    # ---- 右: 因子雷达 + 回测
    with right:
        cats = list(factors.keys())
        radar = go.Figure()
        radar.add_trace(go.Scatterpolar(
            r=[factors[c] for c in cats] + [factors[cats[0]]],
            theta=cats + [cats[0]], fill="toself",
            line_color=info["color"], name="因子分"))
        radar.update_layout(template="plotly_dark", height=300,
                            polar=dict(radialaxis=dict(range=[0, 100])),
                            margin=dict(t=30, b=10), title="因子雷达 (越外越看多)")
        st.plotly_chart(radar, use_container_width=True)

        bt = info["backtest"]
        figb = go.Figure()
        figb.add_trace(go.Scatter(x=bt.index, y=bt["策略"], name="量化策略", line=dict(color="#dc2626", width=2)))
        figb.add_trace(go.Scatter(x=bt.index, y=bt["买入持有"], name="买入持有", line=dict(color="#888", width=1.5, dash="dot")))
        figb.update_layout(template="plotly_dark", height=290, title="策略回测净值",
                           margin=dict(t=30, b=10), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(figb, use_container_width=True)

        s, b = info["stats"], info["bh_stats"]
        if s and b:
            st.markdown("**回测对比**")
            st.dataframe(pd.DataFrame({"量化策略": s, "买入持有": b}).T,
                         use_container_width=True)

    # ---- 新闻情绪面板
    st.markdown(f"### 📰 最新新闻情绪　(情绪因子: {info['factors'].get('新闻情绪', 50)})")
    news_items = info.get("news", [])
    if not news_items:
        st.caption("暂无新闻数据 (或已关闭新闻因子)。")
    else:
        for it in news_items:
            sent = it["sentiment"]
            tag = "🟢 利好" if sent > 0.1 else ("🔴 利空" if sent < -0.1 else "⚪ 中性")
            when = it["when"].strftime("%Y-%m-%d") if it["when"] else "—"
            src = f" · {it['source']}" if it.get("source") else ""
            link = it.get("link") or ""
            title = f"[{it['title']}]({link})" if link else it["title"]
            st.markdown(f"{tag} `{sent:+.2f}`　**{when}**{src}　{title}")

    if info.get("insufficient"):
        st.warning(f"⚠️ {code} 上市仅 {info['n_bars']} 个交易日, 技术指标(均线/MACD/RSI)"
                   "样本不足, 综合分主要参考新闻情绪与短期价格, 仅供观察。")

    st.caption("⚠️ 本工具仅作量化研究参考, 不构成投资建议。实盘请结合基本面与风险承受能力, "
               "在富途牛牛自行决策下单。")


with tab2:
    st.markdown("#### 🔍 个股详情 — 输入代码或名称 (美股英文 / A股中文), 或从自选股选择")
    sc1, sc2, sc3 = st.columns(3)
    us_q = sc1.text_input("🇺🇸 美股 代码/名称", placeholder="如 NVDA 或 apple / nvidia",
                          key="us_query").strip()
    a_q = sc2.text_input("🇨🇳 A股 代码/名称", placeholder="如 600519 或 茅台 / 比亚迪",
                         key="a_query").strip()
    watch_pick = sc3.selectbox(
        "📋 或从自选股选择", options=[""] + list(detail.keys()),
        format_func=lambda t: "（选择自选股…）" if t == "" else f"{t}  {watchlist.get(t, '')}")
    a_news_flag = sc2.checkbox("A股中文新闻情绪 (akshare, 可能较慢)", value=False,
                               key="a_news_detail")

    # 解析目标: (代码, 名称, 货币符号, 是否用新闻)
    target = None
    if us_q:
        cands = search_us_cached(us_q)
        if not cands:
            sc1.warning("未找到匹配的美股，可直接输入代码 (如 NVDA)。")
        else:
            labels = [f"{s} · {n}" + (f" · {cn}" if cn else "") + (f"  ({e})" if e else "")
                      for s, n, cn, e, qt in cands]
            i = sc1.selectbox("匹配结果", range(len(cands)),
                              format_func=lambda i: labels[i], key="us_pick")
            s, n, cn, e, qt = cands[i]
            disp = f"{n} · {cn}" if cn else n
            target = (s, disp, "$", use_news)
    elif a_q:
        cands = search_a_cached(a_q)
        if not cands:
            sc2.warning("未找到匹配的A股，可直接输入6位代码 (如 600519)。")
        else:
            labels = [f"{c} · {n}" for c, n in cands]
            i = sc2.selectbox("匹配结果", range(len(cands)),
                              format_func=lambda i: labels[i], key="a_pick")
            target = (cands[i][0], cands[i][1], "¥", a_news_flag)

    rendered = False
    # 优先级: 搜索(美股>A股) > 自选股 > 默认第一只
    if target:
        code, name, cur, un = target
        info = analyze_single(code, name, period, un, use_fund)
        if not info or info.get("__error__") or "df" not in info:
            st.error(f"未能获取 {code} 的行情数据 (可能未上市/退市/代码有误)。")
        else:
            render_detail(code, info, currency=cur, name=name)
            rendered = True
    elif watch_pick:
        render_detail(watch_pick, detail[watch_pick], currency="$",
                      name=watchlist.get(watch_pick, ""))
        rendered = True

    if not rendered and detail:
        first = list(detail.keys())[0]
        st.caption("👆 在上方输入美股/A股的代码或名称 (支持模糊)，或从自选股下拉选择。"
                   "下方默认显示自选股首只:")
        render_detail(first, detail[first], currency="$", name=watchlist.get(first, ""))

# ================================================================ TAB 8 模拟盘
with tab8:
    st.subheader("🧪 模拟盘 — 把自选股当成一个组合回测")
    st.caption("用量化策略信号(综合分驱动的趋势择时)在历史上逐日调仓, 看整体收益 vs 一直持有不动。"
               "数据来自当前自选股各自的回测, 切换周期/自选股后点『刷新分析』即同步。")

    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        wmode = st.radio("持仓权重", ["等权重 (每日再平衡)", "按综合分加权"],
                         horizontal=False, key="pf_w")
    with c2:
        cap = st.number_input("初始资金", min_value=1000, max_value=100_000_000,
                              value=100_000, step=10_000, key="pf_cap")
    with c3:
        st.caption("　")
        run_pf = st.button("▶ 运行模拟盘", type="primary", use_container_width=True)

    if run_pf or st.session_state.get("pf_done"):
        st.session_state["pf_done"] = True
        wkey = "score" if wmode.startswith("按综合分") else "equal"
        with st.spinner("回测组合净值…"):
            pf = engine.portfolio_backtest(
                detail, names=watchlist, weight=wkey, capital=float(cap))
        if not pf.get("ok"):
            st.warning("自选股回测数据不足, 无法生成模拟盘。请多加几只、拉长数据周期后重试。")
        else:
            ss, bs = pf["strat_stats"], pf["bh_stats"]
            m = st.columns(5)
            m[0].metric("策略总收益", f"{ss.get('总收益%', 0):.1f}%",
                        f"买入持有 {bs.get('总收益%', 0):.1f}%")
            m[1].metric("年化收益", f"{ss.get('年化%', 0):.1f}%",
                        f"{ss.get('年化%', 0) - bs.get('年化%', 0):+.1f}% vs 持有")
            m[2].metric("夏普比率", f"{ss.get('夏普', 0):.2f}")
            m[3].metric("最大回撤", f"{ss.get('最大回撤%', 0):.1f}%",
                        f"持有 {bs.get('最大回撤%', 0):.1f}%", delta_color="inverse")
            m[4].metric("持仓胜率", f"{ss.get('持仓胜率%', 0):.1f}%")

            colf = st.columns(2)
            colf[0].metric(f"策略期末 (投入 {cap:,.0f})", f"{pf['strat_final']:,.0f}")
            colf[1].metric(f"买入持有期末", f"{pf['bh_final']:,.0f}")

            import plotly.graph_objects as _go
            fig = _go.Figure()
            fig.add_trace(_go.Scatter(x=pf["strat_equity"].index,
                                      y=pf["strat_equity"] * cap,
                                      name="策略组合", line=dict(color="#ef5350", width=2)))
            fig.add_trace(_go.Scatter(x=pf["bh_equity"].index,
                                      y=pf["bh_equity"] * cap,
                                      name="买入持有", line=dict(color="#8e9199", width=1.6)))
            fig.update_layout(template="plotly_dark", height=380,
                              title=f"组合净值曲线 ({pf['n']} 只 · {wmode})",
                              yaxis_title="资产", margin=dict(t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("**各标的贡献 (整段回测)**")
            st.dataframe(
                pf["contrib"].style
                .background_gradient(subset=["策略收益%"], cmap="RdYlGn_r")
                .format({"权重%": "{:.1f}", "策略收益%": "{:+.1f}",
                         "买入持有%": "{:+.1f}", "综合分": "{:.1f}"}),
                use_container_width=True, height=min(60 + 36 * len(pf["contrib"]), 460))

            st.info("说明: 策略在『综合分转强(站上均线+MACD向上)』时满仓、转弱时空仓, 逐日执行, 次日成交。"
                    "回撤更小、择时有效时策略会跑赢持有; 单边强牛市里持有可能更高。"
                    "这是历史模拟, 不代表未来收益, 也未计交易成本/滑点。")
    else:
        st.info("点上方『▶ 运行模拟盘』开始。它会用你当前自选股 + 数据周期做组合回测。")

# ================================================================ TAB 9 AI 交易员
with tab9:
    st.subheader("🤖 AI 交易员 — 自动决策的模拟账户")
    st.caption("一个起始虚拟资金的账户, 每次『执行今日交易』会按综合分自动调仓"
               "(≥58 建/加仓到建议仓位·单票≤25%, <45 清仓, 中间持有), "
               "持仓、成交、盈亏曲线全部保存, 像一个会自己操盘的 AI 交易员。"
               "美股 / A股 各一个独立账户。")

    # ---- 市场切换: 美股科技池 / A股龙头池 (各自独立账户)
    _mkt = st.radio("交易市场", ["🇺🇸 美股科技池", "🇨🇳 A股龙头池"],
                    horizontal=True, key="ai_market")
    is_cn = _mkt.startswith("🇨🇳")

    if is_cn:
        res_ai = load_ai_cn(period)
        detail_ai = res_ai.get("detail", {})
        watch_ai = engine.A_SHARE_WATCHLIST
        cur = "¥"
        acc_path = os.path.join(os.path.dirname(paper._DEFAULT_PATH), "paper_account_cn.json")
        default_cash = 1_000_000
        acc_key, lt_key = "acc_cn", "last_trades_cn"
        dl_name = "paper_account_cn.json"
        st.caption(f"当前池: A股龙头 {len(watch_ai)} 只 · 基准 沪深300 · 价格单位 ¥")
    else:
        res_ai = res
        detail_ai = detail
        watch_ai = watchlist
        cur = "$"
        acc_path = paper._DEFAULT_PATH
        default_cash = 100_000
        acc_key, lt_key = "acc", "last_trades"
        dl_name = "paper_account.json"
        st.caption(f"当前池: 美股(侧边栏自选股) {len(watch_ai)} 只 · 基准 QQQ · 价格单位 $")

    if acc_key not in st.session_state:
        st.session_state[acc_key] = paper.load_account(acc_path)
    acc = st.session_state[acc_key]

    ct = st.columns([1, 1, 1, 1.2])
    do_trade = ct[0].button("▶ 执行今日交易", type="primary", use_container_width=True,
                            key=f"trade_{acc_key}")
    do_reset = ct[1].button("↺ 重置账户", use_container_width=True, key=f"reset_{acc_key}")
    init_cash = ct[2].number_input("起始资金", 1000, 1_000_000_000, default_cash, 10_000,
                                   key=f"cap_{acc_key}")
    use_llm = ct[3].checkbox("用大模型写操盘日志 (可选)", value=False, key=f"usellm_{acc_key}",
                             help="不填 Key 用免费规则版; 填 Key 用 DeepSeek/OpenAI 等")

    llm_key = ""
    prov = "deepseek"
    if use_llm:
        # 云端可在 Streamlit Secrets 里配 LLM_API_KEY, 手填优先
        try:
            _sec_key = st.secrets.get("LLM_API_KEY", "")
        except Exception:
            _sec_key = ""
        with st.expander("🔑 大模型 API 设置 (OpenAI 兼容)",
                         expanded=not (_sec_key or llm.has_llm())):
            prov = st.selectbox("服务商", ["deepseek", "openai", "kimi", "qwen"], index=0,
                                key=f"prov_{acc_key}")
            llm_key = st.text_input("API Key", type="password", key=f"key_{acc_key}",
                                    help="仅本次会话使用, 不上传不保存") or _sec_key
            # 存入会话, 供搜索页「AI 研究员点评」共用
            st.session_state["llm_prov"] = prov
            if llm_key:
                st.session_state["llm_key"] = llm_key
            if _sec_key:
                st.caption("✅ 已从 Streamlit Secrets 读到 Key, 无需手填。")
            st.caption("DeepSeek 最便宜(几分钱/次): platform.deepseek.com 拿 sk-xxx。"
                       "留空则自动用免费规则版日志。")

    if do_reset:
        acc = paper.new_account(float(init_cash))
        st.session_state[acc_key] = acc
        paper.save_account(acc, acc_path)
        st.success("账户已重置。")

    last_trades = st.session_state.get(lt_key, [])
    if do_trade:
        if not detail_ai:
            st.warning("当前市场没有可交易的行情数据, 请稍后重试或切换市场。")
        else:
            reg_lbl = (res_ai.get("regime", {}) or {}).get("label", "")
            last_trades = paper.rebalance(acc, detail_ai, names=watch_ai,
                                          reason_regime=reg_lbl)
            paper.save_account(acc, acc_path)
            st.session_state[acc_key] = acc
            st.session_state[lt_key] = last_trades
            if last_trades:
                st.success(f"已执行 {len(last_trades)} 笔调仓。")
            else:
                st.info("今日信号未触发调仓, 维持原持仓。")

    # ---- 账户概览
    summ = paper.summary(acc, detail_ai)
    mc = st.columns(4)
    mc[0].metric("总资产", f"{cur}{summ['total']:,.0f}",
                 f"{summ['ret_pct']:+.1f}% 累计")
    mc[1].metric("现金", f"{cur}{summ['cash']:,.0f}")
    mc[2].metric("持仓市值", f"{cur}{summ['invested']:,.0f}")
    mc[3].metric("持仓数", f"{summ['n_pos']} 只",
                 f"{summ['n_trades']} 笔成交")

    # ---- 操盘日志
    if last_trades or acc.get("last_run"):
        reg_lbl = (res_ai.get("regime", {}) or {}).get("label", "")
        fb = "、".join(f"{r['代码']}{r['盈亏%']:+.0f}%" for r in summ["rows"][:5])
        creds = llm.get_credentials(api_key=llm_key, provider=prov) \
            if use_llm else None
        journal = llm.llm_journal(last_trades, summ, regime=reg_lbl,
                                  factors_brief=fb, creds=creds, cur=cur) if use_llm \
            else llm.rule_based_journal(last_trades, summ, regime=reg_lbl, cur=cur)
        st.markdown("#### 📓 操盘日志")
        st.markdown(journal)

    # ---- 持仓表
    if summ["rows"]:
        st.markdown("#### 📊 当前持仓")
        import pandas as _pd
        dfp = _pd.DataFrame(summ["rows"])
        st.dataframe(
            dfp.style
            .background_gradient(subset=["盈亏%"], cmap="RdYlGn_r", vmin=-30, vmax=30)
            .format({"成本价": "{:.2f}", "现价": "{:.2f}", "市值": "{:,.0f}",
                     "浮动盈亏": "{:,.0f}", "盈亏%": "{:+.1f}", "股数": "{:.2f}"}),
            use_container_width=True, height=min(60 + 36 * len(dfp), 400))
    else:
        st.info("暂无持仓。点『▶ 执行今日交易』让 AI 交易员按信号建仓。")

    # ---- 盈亏曲线
    if len(acc.get("equity_curve", [])) >= 2:
        import plotly.graph_objects as _go
        ec = acc["equity_curve"]
        fig = _go.Figure()
        fig.add_trace(_go.Scatter(x=[p["date"] for p in ec],
                                  y=[p["total"] for p in ec],
                                  name="总资产", line=dict(color="#ef5350", width=2)))
        fig.add_hline(y=acc.get("start_cash", default_cash), line_dash="dash",
                      line_color="#8e9199", annotation_text="起始资金")
        fig.update_layout(template="plotly_dark", height=300,
                          title=f"账户总资产曲线 ({cur})", margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # ---- 成交流水
    if acc.get("trades"):
        with st.expander(f"🧾 成交流水 (共 {len(acc['trades'])} 笔)", expanded=False):
            import pandas as _pd
            dft = _pd.DataFrame(acc["trades"][::-1])
            dft = dft.rename(columns={"date": "时间", "code": "代码", "name": "名称",
                                      "side": "方向", "shares": "股数", "price": "价格",
                                      "amount": "金额", "pnl": "实现盈亏", "reason": "理由"})
            st.dataframe(dft, use_container_width=True, height=320)

    # ---- 备份/恢复
    with st.expander("💾 备份 / 恢复账户", expanded=False):
        import json as _json
        st.download_button("⬇ 下载账户存档 (JSON)",
                           data=_json.dumps(acc, ensure_ascii=False, indent=2),
                           file_name=dl_name, mime="application/json",
                           key=f"dl_{acc_key}")
        up = st.file_uploader("⬆ 上传账户存档恢复", type=["json"], key=f"accup_{acc_key}")
        if up is not None:
            try:
                acc2 = _json.load(up)
                st.session_state[acc_key] = acc2
                paper.save_account(acc2, acc_path)
                st.success("已恢复账户存档, 请重新运行查看。")
            except Exception as _e:
                st.error(f"存档解析失败: {_e}")

    st.caption("⚠️ 纯模拟演示, 不接券商、不下真实订单, 未计交易成本/滑点。仅供研究, 非投资建议。")

# ================================================================ TAB 3 选股池
with tab3:
    st.markdown("#### 🔭 高科技股票池扫描 — 在你持仓之外找机会")
    tech_themes = list(universe.TECH_UNIVERSE.keys())
    sel3 = st.multiselect("① 先选领域 (留空=全部科技主题)", tech_themes, default=[],
                          key="theme_tech", placeholder="选择一个或多个主题…")
    cset = st.columns([1, 1, 2])
    top_n = cset[0].slider("显示前 N 名", 5, 30, 15)
    excl_held = cset[1].checkbox("排除已持仓", value=True)
    cset[2].caption(f"可选主题: {' · '.join(tech_themes)}")

    exclude = set(watchlist.keys()) if excl_held else set()
    if st.button("🔭 开始扫描科技池 (约30-60秒)", key="scan_tech", type="primary") \
            or st.session_state.get("scanned_tech"):
        st.session_state["scanned_tech"] = True
        scr = load_screen("科技", tuple(sorted(exclude)), period, use_fund, top_n,
                          tuple(sel3))
        _render_screen(scr)
    else:
        st.info("先在上方选领域(可留空=全部)，再点按钮开始扫描。")
    st.caption("股票池在 universe.py 里, 可自行增删。扫描默认不含新闻(提速), 缓存 30 分钟。"
               "⚠️ 仅供研究, 非投资建议。")

# ================================================================ TAB 4 美股其他板块
with tab4:
    st.markdown("#### 🇺🇸 美股非科技板块 — 价值/防御/周期, 给科技仓位做分散")
    other_themes = list(universe.US_SECTORS.keys())
    sel4 = st.multiselect("① 先选领域 (留空=全部板块)", other_themes, default=[],
                          key="theme_other", placeholder="选择一个或多个板块…")
    c4a, c4b = st.columns([1, 3])
    topn4 = c4a.slider("显示前 N 名", 5, 30, 15, key="topn4")
    c4b.caption(f"可选板块: {' · '.join(other_themes)}")
    if st.button("🇺🇸 开始扫描非科技板块 (约30-60秒)", key="scan_other", type="primary") \
            or st.session_state.get("scanned_other"):
        st.session_state["scanned_other"] = True
        scr4 = load_screen("非科技", (), period, use_fund, topn4, tuple(sel4))
        _render_screen(scr4)
    else:
        st.info("先在上方选板块(可留空=全部)，再点按钮开始扫描。")
    st.caption("⚠️ 仅供研究, 非投资建议。")

# ================================================================ TAB 5 A股
with tab5:
    st.markdown("#### 🇨🇳 A股龙头选股 — 沪深主要行业龙头")
    a_themes = list(ashare.A_UNIVERSE.keys())
    sel5 = st.multiselect("① 先选行业 (留空=全部行业)", a_themes, default=[],
                          key="theme_a", placeholder="选择一个或多个行业…")
    st.caption("说明: A股无英文新闻因子; 分析师评级部分缺失时取中性。价格为人民币¥。")
    c5a, c5b = st.columns([1, 3])
    topn5 = c5a.slider("显示前 N 名", 5, 30, 15, key="topn5")
    a_news = c5b.checkbox("中文新闻情绪 (akshare, 海外服务器可能超时)", value=False)
    if st.button("🇨🇳 开始扫描A股 (约1-2分钟)", key="scan_a", type="primary") \
            or st.session_state.get("scanned_a"):
        st.session_state["scanned_a"] = True
        scr5 = ashare_screen_cached(period, use_fund, topn5, a_news, tuple(sel5))
        _render_screen(scr5, currency="¥")
    else:
        st.info("先在上方选行业(可留空=全部)，再点按钮开始扫描。注意: 本应用部署在海外服务器, "
                "A股数据 (尤其中文新闻) 可能较慢或超时; 本地运行最稳。")
    st.caption("股票池在 ashare.py 里。沪市.SS/深市.SZ。⚠️ 仅供研究, 非投资建议。")

# ================================================================ TAB 7 指数基金
with tab7:
    st.markdown("#### 💹 指数基金 / ETF — 美国 · 中国 指数择时与轮动")
    st.caption("ETF 无基本面/分析师/财报因子, 打分主看趋势·动量·技术面 + 大盘环境, "
               "适合做指数择时/板块轮动参考。美国ETF为$, 中国ETF为¥。")
    fmkt = st.radio("市场", ["🇺🇸 美国指数", "🇨🇳 中国指数"], horizontal=True, key="fund_mkt")
    is_us = fmkt.startswith("🇺🇸")
    pool = funds.US_INDEX if is_us else funds.CN_INDEX
    cur = "$" if is_us else "¥"
    mkey = "US" if is_us else "CN"

    fsel = st.multiselect("① 先选领域 (留空=全部)", list(pool.keys()), default=[],
                          key=f"theme_fund_{mkey}", placeholder="宽基 / 行业 / 债券黄金 / 主题…")
    fc1, fc2 = st.columns([1, 2])
    topnf = fc1.slider("显示前 N 名", 5, 30, 15, key=f"topnf_{mkey}")
    fq = fc2.text_input("② 或直接搜索单只基金 (代码/中文名, 如 QQQ / 纳斯达克 / 沪深300)",
                        key=f"fund_q_{mkey}", placeholder="留空则走上方扫描").strip()

    # 单只基金详情优先
    if fq:
        cands = search_fund_cached(fq, mkey)
        if not cands:
            st.warning("基金池里未匹配到；可到「个股详情」直接输入 ETF 代码 (如 SPY / 510300.SS)。")
        else:
            i = st.selectbox("匹配结果", range(len(cands)),
                             format_func=lambda i: f"{cands[i][0]} · {cands[i][1]}",
                             key=f"fund_pick_{mkey}")
            fcode, fname = cands[i]
            finfo = analyze_single(fcode, fname, period, False, use_fund)
            if not finfo or finfo.get("__error__") or "df" not in finfo:
                st.error(f"未能获取 {fcode} 的行情数据。")
            else:
                render_detail(fcode, finfo, currency=cur, name=fname)
    else:
        if st.button("💹 开始扫描指数基金 (约30-60秒)", key=f"scan_fund_{mkey}",
                     type="primary") or st.session_state.get(f"scanned_fund_{mkey}"):
            st.session_state[f"scanned_fund_{mkey}"] = True
            scrf = load_fund_screen(mkey, period, use_fund, topnf, tuple(fsel))
            _render_screen(scrf, currency=cur)
        else:
            st.info("先选领域(可留空=全部)再点扫描；或在②直接搜索单只基金看详情。")
    st.caption("基金池在 funds.py 里, 可自行增删。⚠️ 仅供研究, 非投资建议。")


# ================================================================ TAB 6 模型原理
with tab6:
    st.markdown("## 📖 模型用什么指标、怎么「预测」")
    st.warning("先说清楚: 这是一个**多因子打分排序 + 择时**工具, **不是股价预测器**。"
               "没有任何模型能准确预测股价。它的作用是把一篮子股票按「当前性价比」排序, "
               "并给出基于规则的买卖区间。是否有效, 以下方**回测指标(年化/夏普/胜率)**为准。")

    st.markdown("### 综合分 = 11 个因子加权 (0~100 分)　+ 大盘环境微调")
    wdf = pd.DataFrame([
        ["基本面", "14%", "PEG、营收增速、毛利率、ROE、净利率 — 公司值不值这个价", "yfinance"],
        ["趋势", "13%", "价格 vs SMA50/200、金叉死叉、ADX趋势强度 — 方向与强度", "技术"],
        ["分析师", "11%", "华尔街评级均值、目标价上行空间、覆盖分析师数 — 机构怎么看", "yfinance"],
        ["动量", "10%", "MACD、6月/1月涨幅、KDJ随机指标 — 涨势能否延续", "技术"],
        ["盈利质量🆕", "10%", "近4季盈利惊喜(是否连续超预期)、盈利同比增速、预期EPS改善", "yfinance"],
        ["资金流", "9%", "OBV、Chaikin CMF、MFI、放量突破52周高 — 钱在进还是出", "技术"],
        ["筹码面🆕", "8%", "机构持股、内部人持股、做空比例/回补天数 — 主力与空头怎么站队", "yfinance"],
        ["风险", "8%", "年化波动率 — 越稳越高分", "技术"],
        ["相对大盘", "7%", "近63日跑赢/跑输 QQQ(纳指) — 相对强度", "技术"],
        ["新闻情绪", "6%", "美股英文(VADER)/A股中文(akshare) + 金融词典情绪", "新闻"],
        ["强弱", "4%", "RSI、布林带%B — 短期超买超卖", "技术"],
    ], columns=["因子", "权重", "看什么", "来源"])
    st.table(wdf)
    st.markdown("**🌐 大盘环境 (Market Regime)**: 看 QQQ 是否站上 50/200 日线 + 近月动量, "
                "判断 Risk-On/Off。Risk-On 时全局略加分(×1.05)、Risk-Off 时略减分(×0.93) — "
                "顺大势、避免在系统性下跌中满仓。")

    st.markdown("""
### 打分→信号 的规则
| 综合分 | 信号 | 含义 |
|---|---|---|
| ≥70 | 强烈买入 ▲▲ | 多因子共振 |
| 58–70 | 买入 ▲ | 偏多 |
| 45–58 | 持有 — | 中性 |
| 35–45 | 减仓 ▼ | 偏空 |
| <35 | 卖出 ▼▼ | 多因子转弱 |

### 风控怎么算 (下单可直接参考)
- **止损价** = 现价 − 2.5×ATR(平均真实波幅)
- **目标价** = 现价 + 4×ATR (盈亏比约 1.6:1)
- **建议仓位** = 按综合分 × 波动率调整, 单票上限 25% (分越高、波动越低, 仓位越大)
- **财报提醒**: 财报前后波动大, 临近(≤7天)标 ⚠️ 避免追高

### "预测原理"的本质
不是预测某天涨跌, 而是: **当多个相互独立的维度(基本面便宜 + 趋势向上 + 资金流入 + 机构看多 + 消息面正面)同时指向同一方向时, 该股中期占优的概率更高。** 单一指标噪声大, 多因子投票降低误判 — 这是量化选股的核心思想。

### 怎么判断"准不准"
打开 **🔍 个股详情**, 看回测面板: **年化收益、夏普比率、最大回撤、持仓胜率**。
这套策略在该股历史上的真实表现, 比"乍一看准不准"客观得多。

### 🧪 模拟盘 & 🤖 AI 交易员 (新)
- **🧪 模拟盘**: 把整个自选股当一个组合, 用策略信号逐日调仓, 对比"买入持有", 看整体年化/夏普/回撤/胜率与每只标的贡献。
- **🤖 AI 交易员**: 一个起始 $10万 的**持久化虚拟账户** — 每次"执行今日交易"按综合分自动调仓(≥58 建/加仓到建议仓位、单票≤25%; <45 清仓; 中间持有), 保存持仓/成交/盈亏曲线, 并生成"操盘日志"。可选接大模型(DeepSeek/OpenAI 等)把决策写成自然语言; **不填 Key 用免费规则版**。纯模拟, 不接券商、不下真单。

> 完整指标全集: SMA20/50/200、EMA、MACD、RSI、布林带、ATR、ADX/±DI、KDJ、MFI、OBV、CMF、52周高。
""")


# ================================================================ TAB 我的 / 管理
if tab_me is not None:
    with tab_me:
        st.subheader("⚙️ 我的账户与设置")
        _p = userstore.get_profile(CURRENT_USER) or {}
        st.markdown(f"**账户**：{CURRENT_USER}　|　注册：{_p.get('created_at','—')}"
                    f"　|　上次登录：{_p.get('last_login','—')}")

        st.markdown("#### 🔔 推送设置")
        with st.form("me_notify"):
            sk = st.text_input("微信推送 SendKey (Server酱)", value=_p.get("sendkey", "") or "",
                               type="password",
                               help="到 sct.ftqq.com 微信扫码拿 SendKey, 每天操盘播报推到你自己的微信。留空则不推送。")
            nemail = st.text_input("通知邮箱", value=_p.get("notify_email", "") or CURRENT_USER)
            okn = st.form_submit_button("保存推送设置", type="primary")
        if okn:
            if userstore.update_profile(CURRENT_USER, sendkey=sk, notify_email=nemail):
                st.success("推送设置已保存。")
            else:
                st.error("保存失败, 请重试。")

        st.markdown("#### 🔑 修改密码")
        with st.form("me_pw"):
            np1 = st.text_input("新密码 (≥6位)", type="password")
            np2 = st.text_input("确认新密码", type="password")
            okp = st.form_submit_button("更新密码")
        if okp:
            if np1 != np2:
                st.error("两次密码不一致。")
            else:
                good, msg = userstore.change_password(CURRENT_USER, np1)
                (st.success if good else st.error)(msg)

        # 管理员: 所有用户一览
        if auth.is_admin():
            st.divider()
            st.markdown("#### 🛡️ 管理员 · 所有用户")
            _users = userstore.list_users()
            st.caption(f"后端: {userstore.backend_name()}　|　共 {len(_users)} 位用户")
            if _users:
                import pandas as _pd
                _df = _pd.DataFrame(_users)
                for _col in ("email", "created_at", "last_login", "sendkey",
                             "notify_email", "is_admin", "watchlist_text"):
                    if _col not in _df.columns:
                        _df[_col] = ""
                _df["有微信推送"] = _df["sendkey"].apply(lambda x: "✅" if str(x).strip() else "—")
                _show = _df[["email", "is_admin", "created_at", "last_login",
                             "有微信推送", "notify_email"]].rename(
                    columns={"email": "邮箱", "is_admin": "管理员", "created_at": "注册时间",
                             "last_login": "上次登录", "notify_email": "通知邮箱"})
                st.dataframe(_show, use_container_width=True,
                             height=min(80 + 36 * len(_show), 500))
            if userstore.using_supabase():
                st.caption("也可到 Supabase 后台 → Table Editor → users 直接查看/编辑。")

        st.caption("⚠️ 你的 SendKey/邮箱只保存在私有后端, 不进公开仓库, 仅用于给你推送。")