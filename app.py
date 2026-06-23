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
    return engine.analyze(wl, period=period, use_news=use_news, use_fundamentals=use_fund)


@st.cache_data(ttl=1800, show_spinner="🔭 扫描美股股票池中…")
def load_screen(market: str, exclude: tuple, period: str, use_fund: bool, top: int):
    pool = universe.US_SECTORS if market == "非科技" else universe.TECH_UNIVERSE
    return universe.screen(exclude=set(exclude), period=period,
                           use_news=False, use_fundamentals=use_fund, top=top, pool=pool)


@st.cache_data(ttl=1800, show_spinner="🇨🇳 扫描A股龙头中…")
def load_ashare(period: str, use_fund: bool, top: int):
    return ashare.screen(period=period, use_fundamentals=use_fund, top=top)


if refresh:
    load.clear()
    load_screen.clear()
    load_ashare.clear()

res = load(watchlist, period, use_news, use_fund)
table, detail = res["table"], res["detail"]

st.title("📈 美股量化选股看板")
st.caption(f"更新时间: {res['asof']}　·　基准: {engine.BENCHMARK}　·　因子权重: "
           + " ".join(f"{k}{int(v*100)}%" for k, v in engine.WEIGHTS.items()))

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

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["🏆 自选股排名", "🔍 个股详情", "🔭 美股科技池",
     "🇺🇸 美股其他板块", "🇨🇳 A股选股"])


def _render_screen(scr, currency="$"):
    """通用: 渲染一个扫描排名表 + 买入候选汇总。"""
    if scr is None or len(scr) == 0:
        st.warning("未取到数据, 请稍后刷新。")
        return
    cols_scr = [c for c in ["代码", "名称", "主题", "综合分", "信号", "趋势", "动量",
                            "资金流", "基本面", "分析师", "现价", "止损价", "目标价",
                            "建议仓位%"] if c in scr.columns]
    grad = [c for c in ["综合分", "趋势", "动量", "资金流", "基本面", "分析师"] if c in scr.columns]
    fmt = {c: "{:.2f}" for c in ["现价", "止损价", "目标价"] if c in scr.columns}
    fmt["建议仓位%"] = "{:.1f}"
    st.dataframe(
        scr[cols_scr].style
        .background_gradient(subset=grad, cmap="RdYlGn", vmin=0, vmax=100)
        .format(fmt),
        use_container_width=True, height=min(60 + 36 * len(scr), 700))
    buys = scr[scr["综合分"] >= 58]
    if len(buys):
        st.success("**🟢 买入级候选 (综合分≥58)**　" +
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
    factor_cols = [c for c in ["趋势", "动量", "资金流", "基本面", "分析师",
                               "新闻情绪", "强弱", "相对大盘", "风险"] if c in table.columns]
    show_cols = (["代码", "名称", "综合分", "信号"] + factor_cols +
                 ["现价", "止损价", "目标价", "止损%", "目标%", "建议仓位%"])
    disp = table[show_cols].copy()
    st.dataframe(
        disp.style
        .background_gradient(subset=["综合分"], cmap="RdYlGn", vmin=0, vmax=100)
        .background_gradient(subset=factor_cols, cmap="RdYlGn", vmin=0, vmax=100)
        .format({"现价": "{:.2f}", "止损价": "{:.2f}", "目标价": "{:.2f}",
                 "止损%": "{:+.1f}", "目标%": "{:+.1f}", "建议仓位%": "{:.1f}"}),
        use_container_width=True, height=min(60 + 38 * len(disp), 500))

    st.info("**信号解读**　综合分≥70 强烈买入 · 58~70 买入 · 45~58 持有 · "
            "35~45 减仓 · <35 卖出。建议仓位已按波动率调整, 单票上限 25%。"
            "止损/目标价基于 ATR(2.5×/4×), 富途下单时可直接参考。")

# ================================================================ TAB 2 详情
with tab2:
    pick = st.selectbox("选择股票", options=list(detail.keys()),
                        format_func=lambda t: f"{t}  {watchlist.get(t, '')}")
    if pick:
        info = detail[pick]
        d, plan, factors = info["df"], info["plan"], info["factors"]

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("综合分", info["score"])
        c2.metric("信号", info["action"])
        c3.metric("现价", f"${plan['现价']}")
        c4.metric("止损价", f"${plan['止损价']}", f"{plan['止损%']}%")
        c5.metric("目标价", f"${plan['目标价']}", f"{plan['目标%']}%")

        # 基本面 / 分析师 / 资金流 明细
        pd_detail = info.get("plus_detail", {})
        if pd_detail:
            fc1, fc2, fc3 = st.columns(3)
            for col, key, icon in [(fc1, "基本面", "📊"), (fc2, "分析师", "🎯"), (fc3, "资金流", "💰")]:
                dd = pd_detail.get(key, {})
                if dd:
                    txt = "　".join(f"{k} **{v}**" for k, v in dd.items())
                    col.markdown(f"**{icon} {key}** ({info['factors'].get(key,'-')})<br>"
                                 f"<span style='font-size:0.82em'>{txt}</span>",
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
                increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
            for ma, col in [("SMA20", "#f4d35e"), ("SMA50", "#ee964b"), ("SMA200", "#9b5de5")]:
                fig.add_trace(go.Scatter(x=dd.index, y=dd[ma], name=ma,
                                         line=dict(width=1, color=col)), row=1, col=1)
            # 止损/目标参考线
            fig.add_hline(y=plan["止损价"], line=dict(color="#dc2626", dash="dot"), row=1, col=1)
            fig.add_hline(y=plan["目标价"], line=dict(color="#16a34a", dash="dot"), row=1, col=1)

            fig.add_trace(go.Bar(x=dd.index, y=dd["MACD_hist"], name="MACD柱",
                                 marker_color=np.where(dd["MACD_hist"] >= 0, "#26a69a", "#ef5350")), row=2, col=1)
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
            figb.add_trace(go.Scatter(x=bt.index, y=bt["策略"], name="量化策略", line=dict(color="#16a34a", width=2)))
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
            st.warning(f"⚠️ {pick} 上市仅 {info['n_bars']} 个交易日, 技术指标(均线/MACD/RSI)"
                       "样本不足, 综合分主要参考新闻情绪与短期价格, 仅供观察。")

        st.caption("⚠️ 本工具仅作量化研究参考, 不构成投资建议。实盘请结合基本面与风险承受能力, "
                   "在富途牛牛自行决策下单。")

# ================================================================ TAB 3 选股池
with tab3:
    st.markdown("#### 🔭 高科技股票池扫描 — 在你持仓之外找机会")
    cset = st.columns([1, 1, 2])
    top_n = cset[0].slider("显示前 N 名", 5, 30, 15)
    excl_held = cset[1].checkbox("排除已持仓", value=True)
    cset[2].caption(f"覆盖主题: {' · '.join(universe.TECH_UNIVERSE.keys())}")

    exclude = set(watchlist.keys()) if excl_held else set()
    scr = load_screen("科技", tuple(sorted(exclude)), period, use_fund, top_n)
    _render_screen(scr)
    st.caption("股票池在 universe.py 里, 可自行增删。扫描默认不含新闻(提速), 缓存 30 分钟。"
               "⚠️ 仅供研究, 非投资建议。")

# ================================================================ TAB 4 美股其他板块
with tab4:
    st.markdown("#### 🇺🇸 美股非科技板块 — 价值/防御/周期, 给科技仓位做分散")
    st.caption(f"覆盖: {' · '.join(universe.US_SECTORS.keys())}")
    c4a, c4b = st.columns([1, 3])
    topn4 = c4a.slider("显示前 N 名", 5, 30, 15, key="topn4")
    scr4 = load_screen("非科技", (), period, use_fund, topn4)
    _render_screen(scr4)
    st.caption("⚠️ 仅供研究, 非投资建议。")

# ================================================================ TAB 5 A股
with tab5:
    st.markdown("#### 🇨🇳 A股龙头选股 — 沪深主要行业龙头")
    st.caption(f"覆盖: {' · '.join(ashare.A_UNIVERSE.keys())}　|　"
               "说明: A股无英文新闻因子; 分析师评级部分缺失时取中性。价格为人民币¥。")
    c5a, c5b = st.columns([1, 3])
    topn5 = c5a.slider("显示前 N 名", 5, 30, 15, key="topn5")
    scr5 = load_ashare(period, use_fund, topn5)
    _render_screen(scr5, currency="¥")
    st.caption("股票池在 ashare.py 里。沪市.SS/深市.SZ。⚠️ 仅供研究, 非投资建议。")
