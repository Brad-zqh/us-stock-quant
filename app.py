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

import engine
import notify
import universe
import ashare
import resolve

st.set_page_config(page_title="美股量化选股看板", layout="wide", page_icon="📈")

# ---------------------------------------------------------------- 侧边栏配置
st.sidebar.title("⚙️ 配置")
st.sidebar.caption("数据: yfinance 日线 · 仅供研究, 非投资建议")

default_codes = "\n".join(f"{k}  {v}" for k, v in engine.DEFAULT_WATCHLIST.items())
codes_text = st.sidebar.text_area(
    "自选股 (每行: 代码 空格 名称)", value=default_codes, height=200)
period = st.sidebar.selectbox("数据周期", ["1y", "2y", "5y"], index=1)
use_news = st.sidebar.checkbox("启用新闻情绪因子 📰", value=True,
                               help="抓取个股新闻并做金融情绪分析")
use_fund = st.sidebar.checkbox("启用基本面/分析师/资金流 📊", value=True,
                               help="PEG/营收增速/华尔街评级/目标价/OBV/CMF")
refresh = st.sidebar.button("🔄 刷新分析", type="primary", use_container_width=True)

# 解析自选股
watchlist = {}
for line in codes_text.strip().splitlines():
    parts = line.strip().split(None, 1)
    if parts:
        watchlist[parts[0].upper()] = parts[1] if len(parts) > 1 else parts[0]


@st.cache_data(ttl=900, show_spinner="📡 拉取行情并计算中…")
def load(wl: dict, period: str, use_news: bool, use_fund: bool):
    return engine.analyze(wl, period=period, use_news=use_news,
                          use_fundamentals=use_fund, use_earnings=True)


@st.cache_data(ttl=1800, show_spinner="🔭 扫描美股股票池中…")
def load_screen(market: str, exclude: tuple, period: str, use_fund: bool, top: int):
    pool = universe.US_SECTORS if market == "非科技" else universe.TECH_UNIVERSE
    return universe.screen(exclude=set(exclude), period=period,
                           use_news=False, use_fundamentals=use_fund, top=top, pool=pool)


@st.cache_data(ttl=1800, show_spinner="🇨🇳 扫描A股龙头中…")
def ashare_screen_cached(period: str, use_fund: bool, top: int, use_news: bool):
    return ashare.screen(period=period, use_fundamentals=use_fund,
                         top=top, use_news=use_news)


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


if refresh:
    load.clear()
    load_screen.clear()
    ashare_screen_cached.clear()
    analyze_single.clear()
    search_us_cached.clear()
    search_a_cached.clear()

res = load(watchlist, period, use_news, use_fund)
table, detail = res["table"], res["detail"]

st.title("📈 美股量化选股看板")
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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["🏆 自选股排名", "🔍 个股详情", "🔭 美股科技池",
     "🇺🇸 美股其他板块", "🇨🇳 A股选股", "📖 模型原理"])


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

# ================================================================ TAB 3 选股池
with tab3:
    st.markdown("#### 🔭 高科技股票池扫描 — 在你持仓之外找机会")
    cset = st.columns([1, 1, 2])
    top_n = cset[0].slider("显示前 N 名", 5, 30, 15)
    excl_held = cset[1].checkbox("排除已持仓", value=True)
    cset[2].caption(f"覆盖主题: {' · '.join(universe.TECH_UNIVERSE.keys())}")

    exclude = set(watchlist.keys()) if excl_held else set()
    if st.button("🔭 开始扫描科技池 (约30-60秒)", key="scan_tech", type="primary") \
            or st.session_state.get("scanned_tech"):
        st.session_state["scanned_tech"] = True
        scr = load_screen("科技", tuple(sorted(exclude)), period, use_fund, top_n)
        _render_screen(scr)
    else:
        st.info("点上方按钮开始扫描 ~45 只科技龙头。(放在按钮后是为了页面打开够快)")
    st.caption("股票池在 universe.py 里, 可自行增删。扫描默认不含新闻(提速), 缓存 30 分钟。"
               "⚠️ 仅供研究, 非投资建议。")

# ================================================================ TAB 4 美股其他板块
with tab4:
    st.markdown("#### 🇺🇸 美股非科技板块 — 价值/防御/周期, 给科技仓位做分散")
    st.caption(f"覆盖: {' · '.join(universe.US_SECTORS.keys())}")
    c4a, c4b = st.columns([1, 3])
    topn4 = c4a.slider("显示前 N 名", 5, 30, 15, key="topn4")
    if st.button("🇺🇸 开始扫描非科技板块 (约30-60秒)", key="scan_other", type="primary") \
            or st.session_state.get("scanned_other"):
        st.session_state["scanned_other"] = True
        scr4 = load_screen("非科技", (), period, use_fund, topn4)
        _render_screen(scr4)
    else:
        st.info("点上方按钮开始扫描 ~40 只金融/医疗/消费/能源工业/通信龙头。")
    st.caption("⚠️ 仅供研究, 非投资建议。")

# ================================================================ TAB 5 A股
with tab5:
    st.markdown("#### 🇨🇳 A股龙头选股 — 沪深主要行业龙头")
    st.caption(f"覆盖: {' · '.join(ashare.A_UNIVERSE.keys())}　|　"
               "说明: A股无英文新闻因子; 分析师评级部分缺失时取中性。价格为人民币¥。")
    c5a, c5b = st.columns([1, 3])
    topn5 = c5a.slider("显示前 N 名", 5, 30, 15, key="topn5")
    a_news = c5b.checkbox("中文新闻情绪 (akshare, 海外服务器可能超时)", value=False)
    if st.button("🇨🇳 开始扫描A股 (约1-2分钟)", key="scan_a", type="primary") \
            or st.session_state.get("scanned_a"):
        st.session_state["scanned_a"] = True
        scr5 = ashare_screen_cached(period, use_fund, topn5, a_news)
        _render_screen(scr5, currency="¥")
    else:
        st.info("点上方按钮开始扫描 A股龙头。注意: 本应用部署在海外服务器, "
                "A股数据 (尤其中文新闻) 可能较慢或超时; 本地运行最稳。")
    st.caption("股票池在 ashare.py 里。沪市.SS/深市.SZ。⚠️ 仅供研究, 非投资建议。")

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

> 完整指标全集: SMA20/50/200、EMA、MACD、RSI、布林带、ATR、ADX/±DI、KDJ、MFI、OBV、CMF、52周高。
""")
