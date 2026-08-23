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
import orderstore
import favorites
import ui_i18n

T = ui_i18n.t

st.set_page_config(page_title="Brad Quant", layout="wide", page_icon="📈")

ui_i18n.init_language()
ui_i18n.render_language_switcher()

# 多用户登录门 (未启用多用户时返回 None, 保持单用户模式; 未登录会在此停止渲染)
CURRENT_USER = auth.login_gate()

# ---------------------------------------------------------------- 侧边栏配置
st.sidebar.title(T("⚙️ 配置", "⚙️ Settings"))
st.sidebar.caption(T("数据：yfinance 日线 · 仅供研究，不构成投资建议",
                     "Data: yfinance daily bars · Research only, not investment advice"))

# 已登录: 顶部显示用户 + 退出
if CURRENT_USER:
    _uc1, _uc2 = st.sidebar.columns([2, 1])
    _uc1.markdown(f"👤 **{CURRENT_USER}**" + (T("　🛡️管理员", "　🛡️Admin") if auth.is_admin() else ""))
    if _uc2.button(T("退出", "Sign out"), key="logout_btn"):
        auth.logout()
        st.rerun()

# 侧边栏「⭐ 我的收藏」与分析参数在下方 (搜索函数定义之后) 构建, 见 build_watchlist_sidebar()





@st.cache_data(ttl=900, show_spinner=T("📡 正在拉取行情并计算…", "📡 Fetching market data and calculating…"))
def load(wl: dict, period: str, use_news: bool, use_fund: bool):
    return engine.analyze(wl, period=period, use_news=use_news,
                          use_fundamentals=use_fund, use_earnings=True)


@st.cache_data(ttl=1800, show_spinner=T("🔭 正在扫描美股股票池…", "🔭 Scanning the U.S. stock universe…"))
def load_screen(market: str, exclude: tuple, period: str, use_fund: bool, top: int,
                themes: tuple = ()):
    pool_full = universe.US_SECTORS if market == "非科技" else universe.TECH_UNIVERSE
    pool = {k: v for k, v in pool_full.items() if (not themes or k in themes)}
    return universe.screen(exclude=set(exclude), period=period,
                           use_news=False, use_fundamentals=use_fund, top=top, pool=pool)


@st.cache_data(ttl=900, show_spinner=T("🇨🇳 AI 交易员正在拉取A股行情…", "🇨🇳 AI Trader is fetching A-share data…"))
def load_ai_cn(period: str):
    """AI 交易员 A股龙头池独立分析 (与侧边栏美股分析互不影响)。"""
    return engine.analyze(engine.A_SHARE_WATCHLIST, period=period,
                          use_news=False, use_fundamentals=True, use_earnings=False,
                          benchmark=engine.A_BENCHMARK, bench_label="沪深300")


@st.cache_data(ttl=1800, show_spinner=T("🇨🇳 正在扫描A股龙头…", "🇨🇳 Scanning China A-share leaders…"))
def ashare_screen_cached(period: str, use_fund: bool, top: int, use_news: bool,
                         themes: tuple = ()):
    return ashare.screen(period=period, use_fundamentals=use_fund,
                         top=top, use_news=use_news, themes=themes)


@st.cache_data(ttl=1800, show_spinner=T("💹 正在扫描指数基金…", "💹 Scanning ETFs…"))
def load_fund_screen(market: str, period: str, use_fund: bool, top: int, themes: tuple = ()):
    pool_full = funds.US_INDEX if market == "US" else funds.CN_INDEX
    pool = {k: v for k, v in pool_full.items() if (not themes or k in themes)}
    return universe.screen(exclude=set(), period=period, use_news=False,
                           use_fundamentals=use_fund, top=top, pool=pool)


@st.cache_data(ttl=3600, show_spinner=False)
def search_fund_cached(q: str, market: str):
    return funds.search_fund(q, market)


@st.cache_data(ttl=900, show_spinner=T("🔎 正在分析该股票…", "🔎 Analyzing the stock…"))
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


@st.cache_data(ttl=3600, show_spinner=T("🔎 正在匹配A股名称…", "🔎 Matching the A-share company…"))
def search_a_cached(q: str):
    return resolve.search_ashare(q)


@st.cache_data(ttl=86400, show_spinner=False)
def translate_titles_cached(titles: tuple) -> dict:
    """把一批英文新闻标题批量翻成简体中文 (免费接口 + 进程缓存)。
       已是中文/翻译失败 -> 原文。返回 {原文: 中文}。"""
    out = {}
    for t in titles:
        t = (t or "").strip()
        if not t:
            continue
        try:
            out[t] = llm.translate_to_zh(t)
        except Exception:
            out[t] = t
    return out


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


# ============================ 侧边栏: ⭐ 我的收藏 (自选股) ============================
# 常见"名字/别名 -> 正确代码"映射 (避免把公司名当成代码导致取不到行情被丢弃)
_TICKER_ALIAS = {
    "SPACEX": "SPCX", "STARLINK": "SPCX", "星舰": "SPCX", "星链": "SPCX",
    "马斯克": "SPCX", "SPACE-X": "SPCX", "SPACEX星舰": "SPCX",
}

# 默认种子池: 麦迪科技(A股)置顶 + 系统默认池
_MAIDI_LINE = "603990.SS  麦迪科技"
_POOL_LINES = "\n".join(f"{k}  {v}" for k, v in engine.DEFAULT_WATCHLIST.items())
_SEED_CODES = _MAIDI_LINE + "\n" + _POOL_LINES


def _fav_lines() -> list:
    return [ln.strip() for ln in st.session_state.get("fav_text", "").splitlines() if ln.strip()]


def _set_fav(lines: list) -> None:
    st.session_state["fav_text"] = "\n".join(lines)


def _fav_codes_set() -> set:
    return {ln.split(None, 1)[0].upper() for ln in _fav_lines()}


def _add_fav(code: str, name: str) -> bool:
    """加入收藏 (追加到末尾)。已存在返回 False。"""
    code = (code or "").strip()
    if not code:
        return False
    if code.upper() in _fav_codes_set():
        return False
    lines = _fav_lines()
    lines.append(f"{code}  {name}".strip())
    _set_fav(lines)
    return True


# 初始收藏来源优先级: 已登录账户 > 本机 localStorage > 种子池
if "fav_text" not in st.session_state:
    _init = ""
    if CURRENT_USER:
        _prof0 = userstore.get_profile(CURRENT_USER) or {}
        _init = (_prof0.get("watchlist_text") or "").strip()
    if not _init:
        _init = (favorites.load() or "").strip()
    if not _init:
        _init = _SEED_CODES
    st.session_state["fav_text"] = _init
    st.session_state["_fav_persisted"] = (favorites.load() or "").strip()

# 处理来自「个股详情」⭐ 的待加入 (须在 fav_text 文本框实例化前执行, 避免 session_state 冲突)
_pend = st.session_state.pop("_pending_fav_add", None)
if _pend:
    _add_fav(_pend[0], _pend[1])

st.sidebar.markdown(T("### ⭐ 我的收藏", "### ⭐ Favorites"))
st.sidebar.caption(T("搜索名称即可加入，本机自动保存。", "Search by name; saved on this device."))

# —— 搜索并加入收藏
with st.sidebar.expander(T("🔎 搜索并收藏", "🔎 Search & add"), expanded=True):
    _fmkt = st.radio(T("市场", "Market"),
                     [T("🇺🇸 美股", "🇺🇸 U.S. stocks"), T("🇨🇳 A股", "🇨🇳 China A-shares")],
                     horizontal=True, key="fav_mkt")
    _fq = st.text_input(T("代码或名称", "Symbol or name"), key="fav_search_q",
                        placeholder=T("如 NVDA / 苹果，或 麦迪 / 603990",
                                      "e.g. NVDA / Apple or 603990")).strip()
    if _fq:
        if _fmkt.startswith("🇺🇸"):
            _cands = search_us_cached(_fq)
            _opts = [(s, (f"{n} · {cn}" if cn else n)) for s, n, cn, e, qt in _cands]
        else:
            _cands = search_a_cached(_fq)
            _opts = [(c, n) for c, n in _cands]
        if not _opts:
            st.caption(T("没有匹配结果，请更换关键词（A股可用中文名或6位代码）。",
                         "No matches. Try another name or symbol."))
        else:
            _idx = st.selectbox(T("匹配结果", "Matches"), range(len(_opts)),
                                format_func=lambda i: f"{_opts[i][0]}  {_opts[i][1]}",
                                key="fav_pick")
            if st.button(T("➕ 加入收藏", "➕ Add to favorites"), use_container_width=True, key="fav_add_btn"):
                _c, _n = _opts[_idx]
                st.toast((T("已加入收藏：", "Added to favorites: ") + _n)
                         if _add_fav(_c, _n) else T("这只股票已在收藏中。", "Already in favorites."))
                st.rerun()

# 拖拽排序组件 (缺失时自动降级为 ↑ 按钮)
try:
    from streamlit_sortables import sort_items as _sort_items
    _HAS_SORT = True
except Exception:
    _HAS_SORT = False

_SORT_CSS = """
.sortable-component { background: transparent; border: 0; padding: 0; }
.sortable-item, .sortable-item:hover {
  background:#2c3a4b; color:#e8eaed; font-weight:600; font-size:.86em;
  border:1px solid #33404f; border-radius:8px; padding:7px 9px; margin:4px 0;
  cursor:grab; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.sortable-item.dragging { background:#37485c; cursor:grabbing; }
"""

# —— 收藏列表 (拖动排序 / 移除)
_lines = _fav_lines()
# 去重 (拖拽组件要求条目唯一; 正常每只代码唯一, 此处防手动粘贴重复)
_seen = set()
_uniq = []
for _ln in _lines:
    if _ln not in _seen:
        _seen.add(_ln)
        _uniq.append(_ln)
_lines = _uniq

if _lines:
    if _HAS_SORT:
        st.sidebar.caption(T(f"共 {len(_lines)} 只 · 按住拖动排序（顶部优先）",
                             f"{len(_lines)} stocks · Drag to reorder (top first)"))
        with st.sidebar:
            _order = _sort_items(_lines, direction="vertical",
                                 custom_style=_SORT_CSS, key="fav_sort")
        if _order and _order != _lines:
            _set_fav(_order)
            st.rerun()
        # 移除 (可多选)
        _rm = st.sidebar.multiselect(T("移除（可多选）", "Remove (multiple)"), _lines, key="fav_rm_sel",
                                     placeholder=T("选择要移除的股票", "Select stocks to remove"))
        if _rm and st.sidebar.button(T("✕ 移除所选", "✕ Remove selected"), key="fav_rm_btn",
                                     use_container_width=True):
            _set_fav([ln for ln in _lines if ln not in _rm])
            st.rerun()
    else:
        # 降级: 逐行 ↑上移 / ✕移除
        st.sidebar.caption(T(f"共 {len(_lines)} 只 · ↑上移 ✕移除",
                             f"{len(_lines)} stocks · ↑ move up · ✕ remove"))
        for _i, _ln in enumerate(_lines):
            _p = _ln.split(None, 1)
            _code = _p[0]
            _nm = _p[1] if len(_p) > 1 else ""
            _ca, _cb, _cc = st.sidebar.columns([6, 1, 1])
            _ca.markdown(
                f"<div style='font-size:.85em;padding-top:6px;overflow:hidden;white-space:nowrap;"
                f"text-overflow:ellipsis'>{_code} <span style='color:#9aa0aa'>{_nm}</span></div>",
                unsafe_allow_html=True)
            if _cb.button("↑", key=f"fav_up_{_i}", help=T("上移", "Move up"), disabled=(_i == 0)):
                _lines[_i - 1], _lines[_i] = _lines[_i], _lines[_i - 1]
                _set_fav(_lines)
                st.rerun()
            if _cc.button("✕", key=f"fav_rm_{_i}", help=T("移除", "Remove")):
                _lines.pop(_i)
                _set_fav(_lines)
                st.rerun()
else:
    st.sidebar.caption(T("收藏为空——可在上方搜索添加，或在“个股详情”中加入。",
                         "Favorites are empty. Search above or add a stock from Stock details."))

# —— 恢复默认 (放在手动编辑框之前, 避免 widget 已实例化后再改 session_state)
if st.sidebar.button(T("↩️ 恢复默认收藏", "↩️ Restore defaults"), key="fav_reset"):
    _set_fav([ln for ln in _SEED_CODES.splitlines() if ln.strip()])
    st.rerun()

# —— 手动编辑 / 批量粘贴 (高级)
with st.sidebar.expander(T("✏️ 手动编辑 / 批量粘贴", "✏️ Manual edit / bulk paste")):
    st.text_area(T("每行：代码 空格 名称（A股带 .SS/.SZ）",
                   "One per line: symbol, space, name (use .SS/.SZ for A-shares)"),
                 key="fav_text", height=150)
    st.caption(T("例：603990.SS  麦迪科技", "Example: NVDA  Nvidia"))

# —— 已登录: 额外同步到账户 (跨设备)
if CURRENT_USER:
    if st.sidebar.button(T("☁️ 同步到我的账户（跨设备）", "☁️ Sync to my account"), use_container_width=True):
        if userstore.update_profile(CURRENT_USER, watchlist_text=st.session_state["fav_text"]):
            st.sidebar.success(T("已同步到你的账户。", "Synced to your account."))
        else:
            st.sidebar.error(T("同步失败，请重试。", "Sync failed. Please try again."))

st.sidebar.divider()
period = st.sidebar.selectbox(T("数据周期", "Period"), ["1y", "2y", "5y"], index=1)
use_news = st.sidebar.checkbox(T("新闻情绪 📰", "News sentiment 📰"), value=True,
                               help=T("抓取个股新闻并分析财经情绪。",
                                      "Fetch company news and analyze financial sentiment."))
use_fund = st.sidebar.checkbox(T("基本面 / 分析师 / 资金流 📊", "Fundamentals / analysts / money flow 📊"), value=True,
                               help=T("PEG、营收增速、华尔街评级、目标价、OBV、CMF",
                                      "PEG, revenue growth, analyst ratings, target prices, OBV and CMF"))
refresh = st.sidebar.button(T("🔄 刷新分析", "🔄 Refresh analysis"), type="primary", use_container_width=True)

# 本机 localStorage 持久化 (仅在收藏有变化时写一次)
codes_text = st.session_state.get("fav_text", "")
if codes_text.strip() != st.session_state.get("_fav_persisted", ""):
    favorites.save(codes_text)
    st.session_state["_fav_persisted"] = codes_text.strip()

# 解析自选股
watchlist = {}
for line in codes_text.strip().splitlines():
    parts = line.strip().split(None, 1)
    if parts:
        raw = parts[0]
        code = _TICKER_ALIAS.get(raw.upper(), raw.upper())
        name = parts[1] if len(parts) > 1 else (raw if code == raw.upper() else raw)
        watchlist[code] = name


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

st.title(T("📈 皓量化", "📈 Brad Quant"))
st.caption(T("美股 / A股多因子量化选股看板",
             "Multi-factor stock screener for U.S. equities and China A-shares"))

# 提示: 有哪些自选股代码取不到行情被跳过 (未上市/代码错误/退市)
_missing = [f"{c}" + (f"({watchlist[c]})" if watchlist.get(c) and watchlist[c] != c else "")
            for c in watchlist if c not in detail]
if _missing:
    st.warning(T("⚠️ 以下自选股无法取得行情，已跳过（可能未上市、代码有误或已退市）：",
                 "⚠️ No market data were found for these favorites; they were skipped: ")
               + ", ".join(_missing)
               + T("。请改用正确的**交易代码**，例如 SpaceX → `SPCX`。",
                   ". Use the correct **trading symbol**, for example SpaceX → `SPCX`."))

# ---------------------------------------------------------------- 顶部下载 App 入口
_DL_PAGE = "https://brad-zqh.github.io/us-stock-quant/download.html"
_REL = "https://github.com/Brad-zqh/us-stock-quant/releases/latest/download"
_pill = ("text-decoration:none;padding:3px 10px;border-radius:999px;"
         "border:1px solid #2f3640;background:#161b22;color:#e6e6e6;"
         "font-size:0.85em;white-space:nowrap")
st.markdown(
    "<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:-6px 0 10px'>"
    f"<span style='color:#9aa0aa;font-size:0.85em'>{T('📲 下载应用：', '📲 Download app:')}</span>"
    f"<a target='_blank' rel='noopener' style='{_pill}' href='{_REL}/StockQuant-Windows-Setup.exe'>🪟 Windows</a>"
    f"<a target='_blank' rel='noopener' style='{_pill}' href='{_REL}/StockQuant-macOS.dmg'>🍎 macOS</a>"
    f"<a target='_blank' rel='noopener' style='{_pill}' href='{_REL}/StockQuant-Android.apk'>🤖 Android</a>"
    f"<a target='_blank' rel='noopener' style='{_pill};background:#ef5350;border-color:#ef5350;color:#fff' href='{_DL_PAGE}'>{T('📥 全部下载 / iPhone', '📥 All downloads / iPhone')}</a>"
    "</div>", unsafe_allow_html=True)

reg = res.get("regime", {})
if reg:
    rc = {"🟢": "#16a34a", "🟡": "#f59e0b", "🔴": "#dc2626"}.get(reg["label"][:1], "#888")
    st.markdown(
        f"<div style='border-radius:8px;padding:8px 14px;background:#1e1e1e;"
        f"border-left:6px solid {rc};margin-bottom:6px'>"
        f"<b>{T('🌐 大盘环境：', '🌐 Market regime: ')}{reg['label'] if not ui_i18n.is_english() else ('Risk-On' if 'Risk-On' in reg['label'] else ('Risk-Off' if 'Risk-Off' in reg['label'] else 'Neutral'))}</b>　"
        f"({T('择时分', 'Timing score')}: {reg['score']})　"
        f"<span style='color:#999;font-size:0.9em'>{reg['detail'] if not ui_i18n.is_english() else 'Broad-market trend and momentum adjustment'} — "
        f"{T('Risk-On 时全局略加分，Risk-Off 时略减分', 'Risk-On raises scores; Risk-Off lowers scores')}</span></div>", unsafe_allow_html=True)
st.caption(T(f"更新时间：{res['asof']}　·　基准：{engine.BENCHMARK}　·　12因子加权 · 🔴红=看多　🟢绿=看空",
             f"Updated: {res['asof']}　·　Benchmark: {engine.BENCHMARK}　·　12-factor weighted score · 🔴 red = bullish　🟢 green = bearish"))

# ---------------------------------------------------------------- 侧边栏: 推送
st.sidebar.divider()
with st.sidebar.expander(T("📤 推送信号报告（邮件 / 微信）", "📤 Send signal report")):
    st.caption(T("凭证保存在 config.json，不会上传。配置方法见 README。",
                 "Credentials stay in config.json and are never uploaded. See README for setup."))
    cfg = notify.load_config()
    email_ok = bool(cfg.get("email", {}).get("password"))
    wechat_ok = bool(cfg.get("serverchan_key"))
    st.write(T(f"邮件：{'✅ 已配置' if email_ok else '⚠️ 未配置'}　微信：{'✅ 已配置' if wechat_ok else '⚠️ 未配置'}",
               f"Email: {'✅ Configured' if email_ok else '⚠️ Not configured'}　WeChat: {'✅ Configured' if wechat_ok else '⚠️ Not configured'}"))
    cmail = st.checkbox(T("发送邮件", "Send email"), value=email_ok, disabled=not email_ok)
    cwx = st.checkbox(T("推送微信", "Send to WeChat"), value=wechat_ok, disabled=not wechat_ok)
    if st.button(T("立即推送当前信号", "Send current signals now"), use_container_width=True):
        txt, md = notify.build_report(res)
        st.code(txt[:800])
        if cmail:
            st.write(notify.send_email(T("美股量化信号", "U.S. equity quantitative signals"), txt))
        if cwx:
            st.write(notify.send_wechat(T("美股量化信号", "U.S. equity quantitative signals"), md))

def _orders_email():
    """待确认信箱归属的账户: 登录时用登录邮箱; 否则用 FUTU_USER_EMAIL 或管理员邮箱 (与 futu_trader 一致)。"""
    if CURRENT_USER:
        return CURRENT_USER
    e = os.getenv("FUTU_USER_EMAIL", "").strip().lower()
    if e:
        return e
    admins = sorted(userstore.admin_emails())
    return admins[0] if admins else "zhaoqiuhao@zju.edu.cn"


ORDERS_EMAIL = _orders_email()
SHOW_ORDERS = bool(ORDERS_EMAIL)   # 能识别账户才显示"待确认"tab (未配置则隐藏, 零打扰)
try:
    _pending_order_count = len(orderstore.list_pending(ORDERS_EMAIL)) if SHOW_ORDERS else 0
except Exception:
    _pending_order_count = 0

def _render_pending_orders(key_prefix: str = "orders") -> None:
    st.subheader(T("📱 待确认交易", "📱 Pending trade approvals"))
    st.caption(T(f"账户：{ORDERS_EMAIL}　|　信箱后端：{orderstore.backend_name()}",
                 f"Account: {ORDERS_EMAIL}　|　Mailbox backend: {orderstore.backend_name()}"))
    if not orderstore.using_supabase():
        st.info(T("提示：未配置 Supabase 时，只能读取本机 orders.json，云端不可见。"
                  "如需用手机远程确认电脑机器人生成的订单，请配置 Supabase。",
                  "Without Supabase, only the local orders.json file is available. "
                  "Configure Supabase to approve desktop-generated orders remotely."))

    c_a, c_b, c_c = st.columns([1, 1, 1])
    if c_a.button(T("🔄 刷新", "🔄 Refresh"), use_container_width=True, key=f"{key_prefix}_refresh"):
        st.rerun()

    pend = orderstore.list_pending(ORDERS_EMAIL)
    if c_b.button(T(f"✅ 全部确认（{len(pend)}）", f"✅ Approve all ({len(pend)})"), type="primary",
                  use_container_width=True, disabled=not pend,
                  key=f"{key_prefix}_approve_all"):
        n = orderstore.decide_all(ORDERS_EMAIL, approve=True)
        st.success(T(f"已确认 {n} 笔，电脑端执行器运行时会提交到富途。",
                     f"Approved {n} order(s); the desktop executor will submit them to Futu."))
        st.rerun()
    if c_c.button(T("🚫 全部拒绝", "🚫 Reject all"), use_container_width=True, disabled=not pend,
                  key=f"{key_prefix}_reject_all"):
        n = orderstore.decide_all(ORDERS_EMAIL, approve=False)
        st.warning(T(f"已拒绝 {n} 笔。", f"Rejected {n} order(s)."))
        st.rerun()

    if not pend:
        st.success(T("当前没有待确认交易。电脑端运行 `python futu_live_guard.py --push` 后，拟下单会显示在这里。",
                     "There are no pending trades. Run `python futu_live_guard.py --push` on the desktop to send proposed orders here."))
    else:
        st.markdown(T(f"#### 共 {len(pend)} 笔待确认", f"#### {len(pend)} trade(s) awaiting approval"))
        for o in pend:
            side_cn = T("🟢 买入", "🟢 Buy") if o["side"] == "BUY" else T("🔴 卖出", "🔴 Sell")
            envcn = ({"paper": T("模拟盘", "Paper"), "live": T("实盘", "Live"),
                      "live_guard": T("实盘控仓", "Live risk control"),
                      "dry": T("演示", "Dry run")}.get(o.get("env"), o.get("env", "")))
            qty_txt = f"{float(o['qty']):.4f}".rstrip("0").rstrip(".")
            with st.container():
                cc1, cc2, cc3 = st.columns([3, 1, 1])
                cc1.markdown(
                    f"**{side_cn} {o['ticker']}** {o.get('name','')}　`{envcn}`  \n"
                    f"{qty_txt} {T('股', 'shares')} × ${o['price']:.2f} = **${o.get('amount',0):,.0f}**  \n"
                    f"<span style='color:#888'>{o.get('reason','') if not ui_i18n.is_english() else 'Model-generated risk-control instruction.'}</span>",
                    unsafe_allow_html=True)
                if cc2.button(T("确认", "Approve"), key=f"{key_prefix}_ok_{o['id']}", type="primary",
                              use_container_width=True):
                    orderstore.set_status(o["id"], orderstore.STATUS_APPROVED)
                    st.rerun()
                if cc3.button(T("拒绝", "Reject"), key=f"{key_prefix}_no_{o['id']}", use_container_width=True):
                    orderstore.set_status(o["id"], orderstore.STATUS_REJECTED)
                    st.rerun()
                st.divider()

    with st.expander(T("📜 最近交易记录", "📜 Recent trade records")):
        recent = orderstore.list_recent(ORDERS_EMAIL, limit=30)
        if not recent:
            st.caption(T("暂无记录。", "No records yet."))
        else:
            import pandas as _pd
            _emoji = {"done": T("✅已执行", "✅Executed"), "rejected": T("🚫已拒绝", "🚫Rejected"),
                      "failed": T("❌失败", "❌Failed"), "pending": T("⏳待确认", "⏳Pending"),
                      "approved": T("🟡已确认待执行", "🟡Approved"),
                      "executing": T("🔵执行中", "🔵Executing"), "skipped": T("⏭️跳过", "⏭️Skipped")}
            _rows = [{
                T("时间", "Time"): r.get("created_at", ""),
                T("方向", "Side"): T("买", "Buy") if r["side"] == "BUY" else T("卖", "Sell"),
                T("代码", "Symbol"): r["ticker"], T("股数", "Quantity"): r["qty"],
                T("价格", "Price"): r["price"],
                T("状态", "Status"): _emoji.get(r.get("status"), r.get("status", "")),
                T("结果", "Result"): r.get("result", ""),
            } for r in recent]
            st.dataframe(_pd.DataFrame(_rows), use_container_width=True,
                         height=min(80 + 34 * len(_rows), 420))

    st.caption(T("⚠️ 半自动模式：只有在此确认后，电脑执行器才会真正下单。仅供研究，不构成投资建议。",
                 "⚠️ Semi-automated: the desktop executor places an order only after your approval. Research only, not investment advice."))


try:
    _confirm_deep_link = str(st.query_params.get("confirm", "")).lower() in ("1", "true", "yes")
except Exception:
    _confirm_deep_link = False
if _confirm_deep_link:
    st.info(T("这是邮件中的确认入口。请逐笔确认或拒绝；未确认不会下实盘单。",
              "This approval page was opened from an email. Review each order; unapproved orders are never submitted."))
    _render_pending_orders(key_prefix="deep_confirm")
    st.stop()


_order_tab_label = T("📱 待确认", "📱 Confirm")
if _pending_order_count:
    _order_tab_label = T(f"📱 待确认（{_pending_order_count}）", f"📱 Confirm ({_pending_order_count})")

_tab_labels = [T("🔍 个股详情", "🔍 Stock details"), T("🏆 自选股排名", "🏆 Ranking"), _order_tab_label,
               T("🧪 模拟盘", "🧪 Backtest"), T("🤖 AI 交易员", "🤖 AI Trader"),
               T("🔭 美股科技池", "🔭 U.S. Tech"), T("🇺🇸 其他板块", "🇺🇸 U.S. Sectors"),
               T("🇨🇳 A股选股", "🇨🇳 China A-shares"), T("💹 指数基金", "💹 ETFs"),
               T("📖 模型原理", "📖 Methodology")]
if CURRENT_USER:
    _tab_labels.append(T("⚙️ 我的", "⚙️ Account"))
_tabs = st.tabs(_tab_labels)
tab2, tab1, tab_orders, tab8, tab9, tab3, tab4, tab5, tab7, tab6 = _tabs[:10]
_idx = 10
tab_me = _tabs[_idx] if CURRENT_USER else None


_DISPLAY_COLUMNS = {
    "代码": T("代码", "Symbol"), "名称": T("名称", "Name"), "主题": T("主题", "Theme"),
    "综合分": T("综合分", "Score"), "信号": T("信号", "Signal"),
    "基本面": T("基本面", "Fundamentals"), "趋势": T("趋势", "Trend"),
    "分析师": T("分析师", "Analyst"), "动量": T("动量", "Momentum"),
    "盈利质量": T("盈利质量", "Earnings"), "资金流": T("资金流", "Money flow"),
    "筹码面": T("筹码面", "Ownership"), "风险": T("风险", "Risk"),
    "相对大盘": T("相对大盘", "Relative strength"), "板块热度": T("板块热度", "Sector"),
    "新闻情绪": T("新闻情绪", "News"), "强弱": T("强弱", "Oscillator"),
    "现价": T("现价", "Price"), "止损价": T("止损价", "Stop"), "目标价": T("目标价", "Target"),
    "止损%": T("止损%", "Stop %"), "目标%": T("目标%", "Target %"),
    "建议仓位%": T("建议仓位%", "Weight %"), "距财报": T("距财报", "Earnings date"),
}
_ACTION_EN = {
    "强烈买入": T("强烈买入", "Strong Buy"), "买入": T("买入", "Buy"),
    "持有": T("持有", "Hold"), "减仓": T("减仓", "Reduce"),
    "卖出": T("卖出", "Sell"), "观察(次新股)": T("观察（次新股）", "Watch (recent IPO)"),
}
_THEME_EN = {
    "AI算力/半导体": "AI compute / semiconductors", "云与软件": "Cloud / software",
    "互联网/平台": "Internet / platforms", "新能源车/光通信": "EVs / optical networking",
    "金融科技/其他": "Fintech / other", "金融": "Financials", "医疗健康": "Healthcare",
    "消费": "Consumer", "能源/工业": "Energy / industrials", "通信/媒体": "Communication / media",
    "白酒/消费": "Consumer staples", "新能源/电力设备": "Renewables / power equipment",
    "半导体/电子": "Semiconductors / electronics", "医药": "Healthcare", "工业/资源": "Industrials / resources",
    "宽基指数": "Broad market", "行业板块": "Sectors", "债券·黄金·大宗": "Bonds / gold / commodities",
    "主题·成长": "Themes / growth", "中国相关 (美上市)": "China-related U.S. listings",
    "科技·半导体": "Technology / semiconductors", "新能源·制造": "Renewables / manufacturing",
    "金融·地产": "Financials / real estate", "消费·医药": "Consumer / healthcare",
}


def _theme_label(value: str) -> str:
    return _THEME_EN.get(value, value) if ui_i18n.is_english() else value


_DETAIL_EN = {
    "营收增速%": "Revenue growth %", "毛利率%": "Gross margin %", "净利率%": "Net margin %",
    "评级均值": "Average rating", "评级": "Rating", "目标价": "Target price", "上行%": "Upside %",
    "分析师数": "Analysts", "OBV趋势": "OBV trend", "突破": "Breakout", "距52周高%": "From 52-week high %",
    "机构持股%": "Institutional ownership %", "内部人%": "Insider ownership %",
    "做空比例%": "Short interest %", "提示": "Note", "回补天数": "Days to cover",
    "近4季均惊喜%": "Average surprise (4Q) %", "超预期": "Beats", "盈利增速%": "Earnings growth %",
    "EPS预期变化%": "EPS estimate change %", "上升": "Rising", "下降": "Falling",
    "52周新高放量": "Volume-confirmed 52-week high", "近52周高": "Near 52-week high",
    "高做空, 留意逼空": "High short interest; watch for squeeze risk",
}


def _detail_label(value) -> str:
    text = str(value)
    if not ui_i18n.is_english():
        return text
    if text.endswith("次") and text[:-1].replace("/", "").isdigit():
        return text[:-1] + " times"
    return _DETAIL_EN.get(text, text)


def _bilingual_display(df: pd.DataFrame) -> pd.DataFrame:
    """Translate display-only table labels while preserving internal model keys."""
    out = df.copy()
    if "信号" in out.columns:
        out["信号"] = out["信号"].map(lambda x: _ACTION_EN.get(str(x), x))
    return out.rename(columns={c: _DISPLAY_COLUMNS.get(c, c) for c in out.columns})


def _render_screen(scr, currency="$"):
    """通用: 渲染一个扫描排名表 + 买入候选汇总。"""
    if scr is None or len(scr) == 0:
        st.warning(T("未取到数据，请稍后刷新。", "No data are available. Refresh and try again."))
        return
    cols_scr = [c for c in ["代码", "名称", "主题", "综合分", "信号", "基本面", "趋势",
                            "分析师", "动量", "盈利质量", "资金流", "筹码面", "现价",
                            "止损价", "目标价", "建议仓位%"] if c in scr.columns]
    grad = [c for c in ["综合分", "基本面", "趋势", "分析师", "动量", "盈利质量",
                        "资金流", "筹码面"] if c in scr.columns]
    shown = _bilingual_display(scr[cols_scr])
    grad_shown = [_DISPLAY_COLUMNS.get(c, c) for c in grad]
    fmt = {_DISPLAY_COLUMNS.get(c, c): "{:.2f}" for c in ["现价", "止损价", "目标价"] if c in scr.columns}
    fmt[_DISPLAY_COLUMNS["建议仓位%"]] = "{:.1f}"
    st.dataframe(
        shown.style
        .background_gradient(subset=grad_shown, cmap="RdYlGn_r", vmin=0, vmax=100)
        .format(fmt),
        use_container_width=True, height=min(60 + 36 * len(scr), 700))
    buys = scr[scr["综合分"] >= 58]
    if len(buys):
        st.success(T("**🔴 买入级候选（综合分 ≥58）**　", "**🔴 Buy candidates (score ≥58)**　") +
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
                f"<span style='color:{r['_color']}'>{_ACTION_EN.get(str(r['信号']), r['信号'])}</span></div>",
                unsafe_allow_html=True)

    st.markdown("###")
    factor_cols = [c for c in ["基本面", "趋势", "分析师", "动量", "盈利质量", "资金流",
                               "筹码面", "风险", "相对大盘", "板块热度", "新闻情绪", "强弱"]
                   if c in table.columns]
    show_cols = (["代码", "名称", "综合分", "信号"] + factor_cols +
                 ["现价", "止损价", "目标价", "止损%", "目标%", "建议仓位%"] +
                 (["距财报"] if "距财报" in table.columns else []))
    disp = _bilingual_display(table[show_cols])
    factor_cols_display = [_DISPLAY_COLUMNS.get(c, c) for c in factor_cols]
    st.dataframe(
        disp.style
        .background_gradient(subset=[_DISPLAY_COLUMNS["综合分"]], cmap="RdYlGn_r", vmin=0, vmax=100)
        .background_gradient(subset=factor_cols_display, cmap="RdYlGn_r", vmin=0, vmax=100)
        .format({_DISPLAY_COLUMNS["现价"]: "{:.2f}", _DISPLAY_COLUMNS["止损价"]: "{:.2f}",
                 _DISPLAY_COLUMNS["目标价"]: "{:.2f}", _DISPLAY_COLUMNS["止损%"]: "{:+.1f}",
                 _DISPLAY_COLUMNS["目标%"]: "{:+.1f}", _DISPLAY_COLUMNS["建议仓位%"]: "{:.1f}"}),
        use_container_width=True, height=min(60 + 38 * len(disp), 500))

    st.info(T("**信号解读**　综合分 ≥70 强烈买入 · 58–69 买入 · 45–57 持有 · "
              "35–44 减仓 · <35 卖出。建议仓位按波动率调整，单票上限 25%；止损/目标价基于 ATR（2.5×/4×）。",
              "**Signal guide**　Score ≥70 Strong Buy · 58–69 Buy · 45–57 Hold · "
              "35–44 Reduce · <35 Sell. Position sizes are volatility-adjusted with a 25% cap; stop/target levels use ATR (2.5×/4×)."))

# ================================================================ TAB 2 详情
def _english_explanation(info: dict, cur: str) -> dict:
    """Deterministic English explanation for the English-only interface."""
    factor_scores = info.get("factors", {}) or {}
    ranked = sorted(factor_scores.items(), key=lambda item: float(item[1]), reverse=True)
    positives = [f"{_DISPLAY_COLUMNS.get(k, k)}: {v:.0f}/100" for k, v in ranked if float(v) >= 60][:4]
    negatives = [f"{_DISPLAY_COLUMNS.get(k, k)}: {v:.0f}/100" for k, v in reversed(ranked) if float(v) <= 40][:4]
    plan = info.get("plan", {}) or {}
    action = _ACTION_EN.get(str(info.get("action", "")), str(info.get("action", "")))
    return {
        "结论": f"{action}. The composite score is {info.get('score', '—')}/100.",
        "利多": positives,
        "利空": negatives,
        "技术": ["The signal combines trend, momentum, relative strength and oscillator readings."],
        "风控": (f"Risk plan: stop {cur}{plan.get('止损价', '—')}; "
                   f"target {cur}{plan.get('目标价', '—')}; suggested weight {plan.get('建议仓位%', '—')}%."),
        "提示": ["Factor scores are ranking and timing tools, not price forecasts.",
                 "Review fundamentals, liquidity and personal risk tolerance before acting."],
    }


def _english_news_digest(news_items: list) -> str:
    sentiments = [float(item.get("sentiment", 0) or 0) for item in news_items]
    positive = sum(value > 0.1 for value in sentiments)
    negative = sum(value < -0.1 for value in sentiments)
    neutral = len(sentiments) - positive - negative
    tone = "positive" if positive > negative else ("negative" if negative > positive else "mixed")
    return (f"**News snapshot:** {positive} positive, {negative} negative and {neutral} neutral headline(s). "
            f"The recent headline tone is **{tone}**.")


def render_detail(code: str, info: dict, currency: str = "$", name: str = ""):
    """渲染单只股票的完整个股详情面板 (自选股选择 与 搜索 共用)。"""
    cur = currency
    d, plan, factors = info["df"], info["plan"], info["factors"]

    title = f"{code}" + (f"  {name}" if name else "")
    st.markdown(f"#### {title}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(T("综合分", "Score"), info["score"])
    c2.metric(T("信号", "Signal"), _ACTION_EN.get(str(info["action"]), info["action"]))
    c3.metric(T("现价", "Price"), f"{cur}{plan['现价']}")
    c4.metric(T("止损价", "Stop"), f"{cur}{plan['止损价']}", f"{plan['止损%']}%")
    c5.metric(T("目标价", "Target"), f"{cur}{plan['目标价']}", f"{plan['目标%']}%")

    earn = info.get("earnings")
    if earn:
        if earn["soon"]:
            st.error(T(f"⚠️ **财报临近**：{earn['days']} 天后（{earn['date']}）发布财报。财报前后波动通常较大，请谨慎决策。",
                       f"⚠️ **Earnings approaching:** results are due in {earn['days']} day(s) ({earn['date']}). Volatility may increase around the release."))
        else:
            st.caption(T(f"📅 下次财报：{earn['date']}（还有 {earn['days']} 天）",
                         f"📅 Next earnings: {earn['date']} ({earn['days']} days)"))

    # ---- 💡 利好/利空速览 (放最前, 几句话看懂最新消息面; 有 Key 用大模型, 否则规则版)
    news_items = info.get("news", [])
    if news_items:
        dk = f"newsdigest_{code}"
        _creds_d = _llm_creds_from_ui()
        # 页面打开即自动生成 (每只股票只生成一次并缓存; 富途新闻 + 免费翻译, 无需点按钮)
        need_d = st.session_state.get(dk + "_for") != code
        if st.button(T("🔄 重新生成速览", "🔄 Regenerate news snapshot"), key=f"btn_{dk}"):
            need_d = True
        if need_d:
            try:
                if not hasattr(llm, "llm_news_digest"):
                    import importlib
                    importlib.reload(llm)
                with st.spinner(T("正在总结最新利好与利空…", "Summarizing recent news…")):
                    st.session_state[dk] = (_english_news_digest(news_items) if ui_i18n.is_english()
                                            else llm.llm_news_digest(name, news_items, creds=_creds_d))
                    st.session_state[dk + "_for"] = code
            except Exception as _e:
                st.session_state[dk] = T(f"（速览生成失败：{_e}）", f"(Could not generate the news snapshot: {_e})")
                st.session_state[dk + "_for"] = code
        if st.session_state.get(dk):
            st.info(st.session_state[dk])

    # ---- 📝 策略解读 (白话归因)
    try:
        ex = (_english_explanation(info, cur) if ui_i18n.is_english()
              else explain.build_explanation(info, cur=cur, reg=res.get("regime")))
        with st.expander(T("📝 策略解读 — 为什么给出这个信号", "📝 Strategy rationale"), expanded=True):
            st.markdown(f"**{T('🎯 结论', '🎯 Conclusion')}**　{ex['结论']}")
            cL, cR = st.columns(2)
            with cL:
                if ex["利多"]:
                    st.markdown(T("**✅ 支撑看多的因素**", "**✅ Bullish factors**"))
                    for t in ex["利多"]:
                        st.markdown(f"- {t}")
                else:
                    st.markdown(T("**✅ 支撑看多的因素**\n\n- 暂无明显强项因子",
                                  "**✅ Bullish factors**\n\n- No clear factor strength"))
            with cR:
                if ex["利空"]:
                    st.markdown(T("**⚠️ 需要警惕的因素**", "**⚠️ Risk factors**"))
                    for t in ex["利空"]:
                        st.markdown(f"- {t}")
                else:
                    st.markdown(T("**⚠️ 需要警惕的因素**\n\n- 暂无明显弱项因子",
                                  "**⚠️ Risk factors**\n\n- No clear factor weakness"))
            if ex["技术"]:
                st.markdown(T("**📈 技术位置**", "**📈 Technical position**"))
                for t in ex["技术"]:
                    st.markdown(f"- {t}")
            st.markdown(f"**🛡️ {ex['风控']}**")
            for t in ex["提示"]:
                st.markdown(f"> {t}")
            st.caption(T("以上为量化因子的自动归因解读，仅供研究参考，不构成投资建议。",
                         "Automatically generated from quantitative factors. Research only, not investment advice."))
    except Exception as _e:
        st.caption(T(f"（策略解读生成失败：{_e}）", f"(Could not generate the strategy rationale: {_e})"))

    # ---- 🤖 AI 研究员点评 (大模型, 打开即自动生成, 每股缓存一次以控成本)
    with st.expander(T("🤖 AI 研究员点评", "🤖 AI research commentary"), expanded=True):
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
            T("大模型 API Key（可选）", "LLM API key (optional)"), type="password", key=f"aikey_{code}",
            value=st.session_state.get("llm_key", ""),
            placeholder=T("留空则使用免费规则版点评", "Leave blank to use rule-based commentary"),
            help=T("可在 platform.deepseek.com 获取 Key。仅本次会话使用，不保存、不上传。",
                   "Get a key from your provider. It is used only in this session and is not stored or uploaded."))
        prov_in = kc2.selectbox(T("服务商", "Provider"), _provs,
                                index=_provs.index(st.session_state.get("llm_prov", _provs[_pidx]))
                                if st.session_state.get("llm_prov", _provs[_pidx]) in _provs else _pidx,
                                key=f"aiprov_{code}")
        eff_key = key_in or _sec_k
        st.session_state["llm_prov"] = prov_in
        if key_in:
            st.session_state["llm_key"] = key_in      # 同步给 AI 交易员页 & 其他面板
        _creds = llm.get_credentials(api_key=eff_key, provider=prov_in) if eff_key else None

        if _creds:
            st.caption(T(f"✅ 已启用大模型点评（{_creds.get('model')}）。",
                         f"✅ LLM commentary enabled ({_creds.get('model')})."))
        else:
            st.caption(T("ℹ️ 未填写 Key，将使用**免费规则版**点评。",
                         "ℹ️ No API key supplied; **rule-based commentary** will be used."))

        rk = f"aireview_{code}"
        # 打开个股详情即自动生成 (每只股票只生成一次并缓存; 切走再切回不重复计费)
        need = st.session_state.get(rk + "_for") != code
        if st.button(T("🔄 重新生成 AI 点评", "🔄 Regenerate commentary"), key=f"btn_{rk}"):
            need = True
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
                with st.spinner(T("AI 正在综合评述…", "Generating research commentary…")):
                    st.session_state[rk] = ("\n\n".join([
                        ex_t.get("结论", ""),
                        "**Bullish factors**\n" + "\n".join(f"- {x}" for x in ex_t.get("利多", [])),
                        "**Risk factors**\n" + "\n".join(f"- {x}" for x in ex_t.get("利空", [])),
                        ex_t.get("风控", ""),
                    ]) if ui_i18n.is_english() else llm.llm_stock_review(
                        code, name, info.get("score", 0), info.get("action", ""),
                        info.get("factors", {}) or {}, tech=ex_t.get("技术", []),
                        regime=(res.get("regime", {}) or {}).get("label", ""),
                        earnings_soon=bool(_earn.get("soon")), creds=_creds))
                    st.session_state[rk + "_for"] = code
            except Exception as _e:
                st.session_state[rk] = T(f"（AI 点评生成失败：{_e}）", f"(Could not generate commentary: {_e})")
                st.session_state[rk + "_for"] = code
        if st.session_state.get(rk):
            st.markdown(st.session_state[rk])
            st.caption(T("自动生成内容可能存在偏差，仅供研究参考，不构成投资建议。",
                         "Automatically generated content may be inaccurate. Research only, not investment advice."))

    # 基本面 / 分析师 / 资金流 明细
    pd_detail = info.get("plus_detail", {})
    if pd_detail:
        items = [("基本面", "📊"), ("盈利质量", "🚀"), ("分析师", "🎯"),
                 ("筹码面", "🧩"), ("资金流", "💰")]
        ccols = st.columns(len(items))
        for col, (key, icon) in zip(ccols, items):
            dd = pd_detail.get(key, {})
            if dd:
                txt = "　".join(f"{_detail_label(k)} **{_detail_label(v)}**" for k, v in dd.items())
                col.markdown(f"**{icon} {_DISPLAY_COLUMNS.get(key, key)}** ({info['factors'].get(key,'-')})<br>"
                             f"<span style='font-size:0.8em'>{txt}</span>",
                             unsafe_allow_html=True)

    # 原始技术指标读数 (透明化)
    last = d.iloc[-1]
    def _v(col, f="{:.1f}"):
        x = last.get(col)
        return f.format(x) if x is not None and pd.notna(x) else "—"
    st.caption(T(
        f"📐 技术指标　RSI {_v('RSI')}　ADX {_v('ADX')}（>25 趋势强）　KDJ-J {_v('J')}　"
        f"MFI {_v('MFI')}（>80 超买 / <20 超卖）　CMF {_v('CMF','{:.3f}')}　"
        f"布林 %B {_v('BB_pctB','{:.2f}')}　年化波动 {_v('vol_ann','{:.0%}')}",
        f"📐 Technical indicators　RSI {_v('RSI')}　ADX {_v('ADX')} (>25 strong trend)　KDJ-J {_v('J')}　"
        f"MFI {_v('MFI')} (>80 overbought / <20 oversold)　CMF {_v('CMF','{:.3f}')}　"
        f"Bollinger %B {_v('BB_pctB','{:.2f}')}　Annualized volatility {_v('vol_ann','{:.0%}')}"))

    left, right = st.columns([3, 2])

    # ---- 左: K线 + 均线 + MACD + RSI
    with left:
        dd = d.tail(180)
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                            row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
                            subplot_titles=(T("K线 + 均线", "Candles + moving averages"), "MACD", "RSI"))
        fig.add_trace(go.Candlestick(
            x=dd.index, open=dd["Open"], high=dd["High"], low=dd["Low"],
            close=dd["Close"], name=T("K线", "Candles"),
            increasing_line_color="#ef5350", decreasing_line_color="#26a69a"), row=1, col=1)
        for ma, col in [("SMA20", "#f4d35e"), ("SMA50", "#ee964b"), ("SMA200", "#9b5de5")]:
            fig.add_trace(go.Scatter(x=dd.index, y=dd[ma], name=ma,
                                     line=dict(width=1, color=col)), row=1, col=1)
        # 止损/目标参考线
        fig.add_hline(y=plan["止损价"], line=dict(color="#16a34a", dash="dot"), row=1, col=1)
        fig.add_hline(y=plan["目标价"], line=dict(color="#dc2626", dash="dot"), row=1, col=1)

        fig.add_trace(go.Bar(x=dd.index, y=dd["MACD_hist"], name=T("MACD柱", "MACD histogram"),
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
        cats_display = [_DISPLAY_COLUMNS.get(cat, cat) for cat in cats]
        radar = go.Figure()
        radar.add_trace(go.Scatterpolar(
            r=[factors[c] for c in cats] + [factors[cats[0]]],
            theta=cats_display + [cats_display[0]], fill="toself",
            line_color=info["color"], name=T("因子分", "Factor score")))
        radar.update_layout(template="plotly_dark", height=300,
                            polar=dict(radialaxis=dict(range=[0, 100])),
                            margin=dict(t=30, b=10), title=T("因子雷达（越外越看多）", "Factor radar (farther out is stronger)"))
        st.plotly_chart(radar, use_container_width=True)

        bt = info["backtest"]
        figb = go.Figure()
        figb.add_trace(go.Scatter(x=bt.index, y=bt["策略"], name=T("量化策略", "Strategy"), line=dict(color="#dc2626", width=2)))
        figb.add_trace(go.Scatter(x=bt.index, y=bt["买入持有"], name=T("买入持有", "Buy & hold"), line=dict(color="#888", width=1.5, dash="dot")))
        figb.update_layout(template="plotly_dark", height=290, title=T("策略回测净值", "Backtest equity curve"),
                           margin=dict(t=30, b=10), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(figb, use_container_width=True)

        s, b = info["stats"], info["bh_stats"]
        if s and b:
            st.markdown(T("**回测对比**", "**Backtest comparison**"))
            _stat_cols = {"总收益%": T("总收益%", "Total return %"), "年化%": T("年化%", "Annualized %"),
                          "夏普": T("夏普", "Sharpe"), "最大回撤%": T("最大回撤%", "Max drawdown %"),
                          "持仓胜率%": T("持仓胜率%", "In-position win rate %")}
            _stats_table = pd.DataFrame({T("量化策略", "Strategy"): s,
                                         T("买入持有", "Buy & hold"): b}).T.rename(columns=_stat_cols)
            st.dataframe(_stats_table,
                         use_container_width=True)

    # ---- 新闻情绪面板
    st.markdown(T(f"### 📰 最新新闻情绪（情绪因子：{info['factors'].get('新闻情绪', 50)}）",
                  f"### 📰 Latest news sentiment (factor: {info['factors'].get('新闻情绪', 50)})"))
    news_items = info.get("news", [])
    if not news_items:
        st.caption(T("暂无新闻数据（或新闻因子已关闭）。", "No news data are available, or the news factor is disabled."))
    else:
        st.caption(T("💡 本页上方的新闻速览提供简要总结。", "💡 See the news snapshot above for a concise summary."))
        bi = not ui_i18n.is_english()
        trans = {}
        if bi:
            _titles = tuple(dict.fromkeys(
                str(it.get("title", "")).strip() for it in news_items
                if str(it.get("title", "")).strip()))
            with st.spinner("正在翻译新闻标题…"):
                trans = translate_titles_cached(_titles)
        with st.expander(T("展开逐条新闻", "Show individual headlines"), expanded=True):
            for it in news_items:
                sent = it["sentiment"]
                tag = (T("🟢 利好", "🟢 Positive") if sent > 0.1 else
                       (T("🔴 利空", "🔴 Negative") if sent < -0.1 else T("⚪ 中性", "⚪ Neutral")))
                when = it["when"].strftime("%Y-%m-%d") if it["when"] else "—"
                src = f" · {it['source']}" if it.get("source") else ""
                link = it.get("link") or ""
                en = it["title"]
                zh = trans.get(en.strip(), "") if bi else ""
                show = zh if (zh and zh != en) else en
                title = f"[{show}]({link})" if link else show
                st.markdown(f"{tag} `{sent:+.2f}`　**{when}**{src}　{title}")

    if info.get("insufficient"):
        st.warning(T(f"⚠️ {code} 上市仅 {info['n_bars']} 个交易日，均线、MACD、RSI 等指标样本不足；综合分仅供观察。",
                     f"⚠️ {code} has only {info['n_bars']} trading days of history. Long-window indicators are incomplete; treat the score as preliminary."))

    st.caption(T("⚠️ 本工具仅供量化研究，不构成投资建议。实盘决策请结合基本面与个人风险承受能力。",
                 "⚠️ Quantitative research only, not investment advice. Consider fundamentals and your own risk tolerance before trading."))


with tab2:
    st.markdown(T("#### 🔍 个股详情 — 输入代码或名称", "#### 🔍 Stock details — enter a symbol or company name"))
    sc1, sc2, sc3 = st.columns(3)
    us_q = sc1.text_input(T("🇺🇸 美股代码 / 名称", "🇺🇸 U.S. symbol / company"),
                          placeholder=T("如 NVDA 或 Apple", "e.g. NVDA or Apple"),
                          key="us_query").strip()
    a_q = sc2.text_input(T("🇨🇳 A股代码 / 名称", "🇨🇳 China A-share symbol / company"),
                         placeholder=T("如 600519 或 茅台", "e.g. 600519"),
                         key="a_query").strip()
    watch_pick = sc3.selectbox(
        T("📋 或从自选股选择", "📋 Or choose from favorites"), options=[""] + list(detail.keys()),
        format_func=lambda t: T("（选择自选股…）", "(Choose a favorite…)") if t == "" else f"{t}  {watchlist.get(t, '')}")
    a_news_flag = sc2.checkbox(T("A股新闻情绪 📰（富途新闻源）", "A-share news sentiment 📰 (Futu)"), value=True,
                               key="a_news_detail")

    # 解析目标: (代码, 名称, 货币符号, 是否用新闻)
    target = None
    if us_q:
        cands = search_us_cached(us_q)
        if not cands:
            sc1.warning(T("未找到匹配的美股，可直接输入代码（如 NVDA）。",
                          "No matching U.S. stock was found. Try a symbol such as NVDA."))
        else:
            labels = [f"{s} · {n}" + (f" · {cn}" if cn else "") + (f"  ({e})" if e else "")
                      for s, n, cn, e, qt in cands]
            i = sc1.selectbox(T("匹配结果", "Matches"), range(len(cands)),
                              format_func=lambda i: labels[i], key="us_pick")
            s, n, cn, e, qt = cands[i]
            disp = f"{n} · {cn}" if cn else n
            target = (s, disp, "$", use_news)
    elif a_q:
        cands = search_a_cached(a_q)
        if not cands:
            sc2.warning(T("未找到匹配的A股，可直接输入6位代码（如 600519）。",
                          "No matching A-share was found. Try a six-digit symbol such as 600519."))
        else:
            labels = [f"{c} · {n}" for c, n in cands]
            i = sc2.selectbox(T("匹配结果", "Matches"), range(len(cands)),
                              format_func=lambda i: labels[i], key="a_pick")
            target = (cands[i][0], cands[i][1], "¥", a_news_flag)

    rendered = False
    # 优先级: 搜索(美股>A股) > 自选股 > 默认第一只
    if target:
        code, name, cur, un = target
        info = analyze_single(code, name, period, un, use_fund)
        if not info or info.get("__error__") or "df" not in info:
            st.error(T(f"未能获取 {code} 的行情数据（可能未上市、已退市或代码有误）。",
                       f"Could not retrieve market data for {code}; verify the listing and symbol."))
        else:
            render_detail(code, info, currency=cur, name=name)
            rendered = True
            _in_fav = code.upper() in _fav_codes_set()
            if st.button((T("⭐ 已在收藏", "⭐ In favorites") if _in_fav else T("⭐ 加入收藏", "⭐ Add to favorites")),
                         key="detail_add_fav", disabled=_in_fav):
                st.session_state["_pending_fav_add"] = (code, name)
                st.toast(T(f"已加入收藏：{name}", f"Added to favorites: {name}"))
                st.rerun()
    elif watch_pick:
        render_detail(watch_pick, detail[watch_pick], currency="$",
                      name=watchlist.get(watch_pick, ""))
        rendered = True

    if not rendered and detail:
        first = list(detail.keys())[0]
        st.caption(T("👆 在上方输入美股 / A股代码或名称（支持模糊搜索），或从自选股中选择。下方默认显示第一只自选股：",
                     "👆 Enter a U.S. or China A-share symbol/company above, or choose a favorite. The first favorite is shown by default:"))
        render_detail(first, detail[first], currency="$", name=watchlist.get(first, ""))

# ================================================================ TAB 8 模拟盘
with tab8:
    st.subheader(T("🧪 模拟盘 — 自选股组合回测", "🧪 Portfolio backtest — test favorites as one portfolio"))
    st.caption(T("按综合分驱动的趋势信号逐日调仓，对比策略收益与买入持有。切换周期或自选股后请刷新分析。",
                 "Rebalance daily using score-driven trend signals and compare the strategy with buy-and-hold. Refresh after changing the period or favorites."))

    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        _wmode_options = [T("等权重（每日再平衡）", "Equal weight (daily rebalance)"),
                          T("按综合分加权", "Score weighted")]
        wmode = st.radio(T("持仓权重", "Portfolio weighting"), _wmode_options,
                         horizontal=False, key="pf_w")
    with c2:
        cap = st.number_input(T("初始资金", "Initial capital"), min_value=1000, max_value=100_000_000,
                              value=100_000, step=10_000, key="pf_cap")
    with c3:
        st.caption("　")
        run_pf = st.button(T("▶ 运行模拟盘", "▶ Run backtest"), type="primary", use_container_width=True)

    if run_pf or st.session_state.get("pf_done"):
        st.session_state["pf_done"] = True
        wkey = "score" if wmode == _wmode_options[1] else "equal"
        with st.spinner(T("正在回测组合净值…", "Backtesting the portfolio…")):
            pf = engine.portfolio_backtest(
                detail, names=watchlist, weight=wkey, capital=float(cap))
        if not pf.get("ok"):
            st.warning(T("自选股回测数据不足。请增加股票或延长数据周期后重试。",
                         "There are not enough observations. Add stocks or use a longer period."))
        else:
            ss, bs = pf["strat_stats"], pf["bh_stats"]
            m = st.columns(5)
            m[0].metric(T("策略总收益", "Strategy return"), f"{ss.get('总收益%', 0):.1f}%",
                        T(f"买入持有 {bs.get('总收益%', 0):.1f}%", f"Buy & hold {bs.get('总收益%', 0):.1f}%"))
            m[1].metric(T("年化收益", "Annualized return"), f"{ss.get('年化%', 0):.1f}%",
                        T(f"较持有 {ss.get('年化%', 0) - bs.get('年化%', 0):+.1f}%",
                          f"{ss.get('年化%', 0) - bs.get('年化%', 0):+.1f}% vs hold"))
            m[2].metric(T("夏普比率", "Sharpe ratio"), f"{ss.get('夏普', 0):.2f}")
            m[3].metric(T("最大回撤", "Maximum drawdown"), f"{ss.get('最大回撤%', 0):.1f}%",
                        T(f"持有 {bs.get('最大回撤%', 0):.1f}%", f"Hold {bs.get('最大回撤%', 0):.1f}%"), delta_color="inverse")
            m[4].metric(T("持仓胜率", "In-position win rate"), f"{ss.get('持仓胜率%', 0):.1f}%")

            colf = st.columns(2)
            colf[0].metric(T(f"策略期末（投入 {cap:,.0f}）", f"Strategy final value (from {cap:,.0f})"), f"{pf['strat_final']:,.0f}")
            colf[1].metric(T("买入持有期末", "Buy & hold final value"), f"{pf['bh_final']:,.0f}")

            import plotly.graph_objects as _go
            fig = _go.Figure()
            fig.add_trace(_go.Scatter(x=pf["strat_equity"].index,
                                      y=pf["strat_equity"] * cap,
                                      name=T("策略组合", "Strategy"), line=dict(color="#ef5350", width=2)))
            fig.add_trace(_go.Scatter(x=pf["bh_equity"].index,
                                      y=pf["bh_equity"] * cap,
                                      name=T("买入持有", "Buy & hold"), line=dict(color="#8e9199", width=1.6)))
            fig.update_layout(template="plotly_dark", height=380,
                              title=T(f"组合净值曲线（{pf['n']} 只 · {wmode}）", f"Portfolio equity curve ({pf['n']} assets · {wmode})"),
                              yaxis_title=T("资产", "Equity"), margin=dict(t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)

            st.markdown(T("**各标的贡献（完整回测期）**", "**Contribution by asset (full backtest)**"))
            _contrib_cols = {"代码": T("代码", "Symbol"), "名称": T("名称", "Name"),
                             "权重%": T("权重%", "Weight %"), "策略收益%": T("策略收益%", "Strategy return %"),
                             "买入持有%": T("买入持有%", "Buy & hold %"), "综合分": T("综合分", "Score")}
            _contrib = pf["contrib"].rename(columns=_contrib_cols)
            st.dataframe(
                _contrib.style
                .background_gradient(subset=[_contrib_cols["策略收益%"]], cmap="RdYlGn_r")
                .format({_contrib_cols["权重%"]: "{:.1f}", _contrib_cols["策略收益%"]: "{:+.1f}",
                         _contrib_cols["买入持有%"]: "{:+.1f}", _contrib_cols["综合分"]: "{:.1f}"}),
                use_container_width=True, height=min(60 + 36 * len(pf["contrib"]), 460))

            st.info(T("策略在综合分转强时持仓、转弱时空仓，信号次日成交。历史模拟不代表未来收益，且未计交易成本与滑点。",
                      "The strategy holds when the score strengthens and exits when it weakens; signals trade the next day. Historical simulation does not predict future returns and excludes costs and slippage."))
    else:
        st.info(T("点击“▶ 运行模拟盘”，使用当前自选股和数据周期开始组合回测。",
                  "Select “▶ Run backtest” to test the current favorites over the selected period."))

# ================================================================ TAB 9 AI 交易员
with tab9:
    st.subheader(T("🤖 AI 交易员 — 自动决策的模拟账户", "🤖 AI Trader — automated paper account"))
    st.caption(T("每次执行今日交易时，系统按综合分自动调仓：≥58 建仓或加仓，<45 清仓，单票不超过 25%。美股与 A股账户相互独立。",
                 "Each run rebalances from composite scores: build/add at ≥58, exit below 45, and cap each position at 25%. U.S. and China A-share accounts are separate."))

    # ---- 市场切换: 美股科技池 / A股龙头池 (各自独立账户)
    _mkt = st.radio(T("交易市场", "Market"),
                    [T("🇺🇸 美股科技池", "🇺🇸 U.S. favorites"), T("🇨🇳 A股龙头池", "🇨🇳 China A-share leaders")],
                    horizontal=True, key="ai_market")
    is_cn = _mkt.startswith("🇨🇳")

    if is_cn:
        res_ai = load_ai_cn(period)
        detail_ai = res_ai.get("detail", {})
        watch_ai = engine.A_SHARE_WATCHLIST
        cur = "¥"
        acc_path = os.path.join(os.path.dirname(paper._DEFAULT_PATH), "paper_account_cn.json")
        default_cash = 30_000
        acc_key, lt_key = "acc_cn", "last_trades_cn"
        dl_name = "paper_account_cn.json"
        st.caption(T(f"当前池：A股龙头 {len(watch_ai)} 只 · 基准 沪深300 · 价格单位 ¥",
                     f"Current universe: {len(watch_ai)} China A-share leaders · Benchmark: CSI 300 · Currency: ¥"))
    else:
        res_ai = res
        detail_ai = detail
        watch_ai = watchlist
        cur = "$"
        acc_path = paper._DEFAULT_PATH
        default_cash = 100_000
        acc_key, lt_key = "acc", "last_trades"
        dl_name = "paper_account.json"
        st.caption(T(f"当前池：美股自选股 {len(watch_ai)} 只 · 基准 QQQ · 价格单位 $",
                     f"Current universe: {len(watch_ai)} U.S. favorites · Benchmark: QQQ · Currency: $"))

    if acc_key not in st.session_state:
        st.session_state[acc_key] = paper.load_account(acc_path)
    acc = st.session_state[acc_key]

    ct = st.columns([1, 1, 1, 1.2])
    do_trade = ct[0].button(T("▶ 执行今日交易", "▶ Run today's trades"), type="primary", use_container_width=True,
                            key=f"trade_{acc_key}")
    do_reset = ct[1].button(T("↺ 重置账户", "↺ Reset account"), use_container_width=True, key=f"reset_{acc_key}")
    init_cash = ct[2].number_input(T("起始资金", "Starting capital"), 1000, 1_000_000_000, default_cash, 10_000,
                                   key=f"cap_{acc_key}")
    use_llm = ct[3].checkbox(T("使用大模型生成操盘日志（可选）", "Use an LLM for the trading journal (optional)"),
                             value=False, key=f"usellm_{acc_key}",
                             help=T("不填 Key 时使用免费规则版。", "Without a key, the rule-based journal is used."))

    llm_key = ""
    prov = "deepseek"
    if use_llm:
        # 云端可在 Streamlit Secrets 里配 LLM_API_KEY, 手填优先
        try:
            _sec_key = st.secrets.get("LLM_API_KEY", "")
        except Exception:
            _sec_key = ""
        with st.expander(T("🔑 大模型 API 设置（OpenAI 兼容）", "🔑 LLM API settings (OpenAI-compatible)"),
                         expanded=not (_sec_key or llm.has_llm())):
            prov = st.selectbox(T("服务商", "Provider"), ["deepseek", "openai", "kimi", "qwen"], index=0,
                                key=f"prov_{acc_key}")
            llm_key = st.text_input("API Key", type="password", key=f"key_{acc_key}",
                                    help=T("仅本次会话使用，不上传、不保存。",
                                           "Used only in this session; never uploaded or stored.")) or _sec_key
            # 存入会话, 供搜索页「AI 研究员点评」共用
            st.session_state["llm_prov"] = prov
            if llm_key:
                st.session_state["llm_key"] = llm_key
            if _sec_key:
                st.caption(T("✅ 已从 Streamlit Secrets 读取 Key，无需手填。",
                             "✅ API key loaded from Streamlit Secrets."))
            st.caption(T("可在 platform.deepseek.com 获取 DeepSeek Key；留空则使用免费规则版日志。",
                         "Get a DeepSeek key at platform.deepseek.com, or leave blank for the rule-based journal."))

    if do_reset:
        acc = paper.new_account(float(init_cash))
        st.session_state[acc_key] = acc
        paper.save_account(acc, acc_path)
        st.success(T("账户已重置。", "Account reset."))

    last_trades = st.session_state.get(lt_key, [])
    if do_trade:
        if not detail_ai:
            st.warning(T("当前市场没有可交易行情，请稍后重试或切换市场。",
                         "No tradable market data are available. Try again later or switch markets."))
        else:
            reg_lbl = (res_ai.get("regime", {}) or {}).get("label", "")
            last_trades = paper.rebalance(acc, detail_ai, names=watch_ai,
                                          reason_regime=reg_lbl)
            paper.save_account(acc, acc_path)
            st.session_state[acc_key] = acc
            st.session_state[lt_key] = last_trades
            if last_trades:
                st.success(T(f"已执行 {len(last_trades)} 笔调仓。", f"Executed {len(last_trades)} rebalance trade(s)."))
            else:
                st.info(T("今日信号未触发调仓，维持原持仓。", "Today's signals did not trigger a rebalance; positions are unchanged."))

    # ---- 账户概览
    summ = paper.summary(acc, detail_ai)
    mc = st.columns(4)
    mc[0].metric(T("总资产", "Total equity"), f"{cur}{summ['total']:,.0f}",
                 T(f"{summ['ret_pct']:+.1f}% 累计", f"{summ['ret_pct']:+.1f}% cumulative"))
    mc[1].metric(T("现金", "Cash"), f"{cur}{summ['cash']:,.0f}")
    mc[2].metric(T("持仓市值", "Invested value"), f"{cur}{summ['invested']:,.0f}")
    mc[3].metric(T("持仓数", "Positions"), T(f"{summ['n_pos']} 只", f"{summ['n_pos']} assets"),
                 T(f"{summ['n_trades']} 笔成交", f"{summ['n_trades']} trades"))

    # ---- 操盘日志
    if last_trades or acc.get("last_run"):
        reg_lbl = (res_ai.get("regime", {}) or {}).get("label", "")
        fb = "、".join(f"{r['代码']}{r['盈亏%']:+.0f}%" for r in summ["rows"][:5])
        creds = llm.get_credentials(api_key=llm_key, provider=prov) \
            if use_llm else None
        if ui_i18n.is_english():
            journal = (f"The model processed {len(last_trades)} trade(s). Portfolio equity is "
                       f"{cur}{summ['total']:,.0f}, with {summ['ret_pct']:+.1f}% cumulative return. "
                       f"The account currently holds {summ['n_pos']} position(s).")
        else:
            journal = llm.llm_journal(last_trades, summ, regime=reg_lbl,
                                      factors_brief=fb, creds=creds, cur=cur) if use_llm \
                else llm.rule_based_journal(last_trades, summ, regime=reg_lbl, cur=cur)
        st.markdown(T("#### 📓 操盘日志", "#### 📓 Trading journal"))
        st.markdown(journal)

    # ---- 持仓表
    if summ["rows"]:
        st.markdown(T("#### 📊 当前持仓", "#### 📊 Current positions"))
        import pandas as _pd
        dfp = _pd.DataFrame(summ["rows"])
        _pos_cols = {"代码": T("代码", "Symbol"), "名称": T("名称", "Name"),
                     "股数": T("股数", "Shares"), "成本价": T("成本价", "Cost"),
                     "现价": T("现价", "Price"), "市值": T("市值", "Market value"),
                     "浮动盈亏": T("浮动盈亏", "Unrealized P/L"), "盈亏%": T("盈亏%", "P/L %")}
        dfp = dfp.rename(columns=_pos_cols)
        _pnl_col = _pos_cols["盈亏%"]
        st.dataframe(
            dfp.style
            .background_gradient(subset=[_pnl_col], cmap="RdYlGn_r", vmin=-30, vmax=30)
            .format({_pos_cols["成本价"]: "{:.2f}", _pos_cols["现价"]: "{:.2f}", _pos_cols["市值"]: "{:,.0f}",
                     _pos_cols["浮动盈亏"]: "{:,.0f}", _pnl_col: "{:+.1f}", _pos_cols["股数"]: "{:.2f}"}),
            use_container_width=True, height=min(60 + 36 * len(dfp), 400))
    else:
        st.info(T("暂无持仓。点击“▶ 执行今日交易”，让 AI 交易员按信号建仓。",
                  "No positions. Select “▶ Run today's trades” to let the AI Trader act on current signals."))

    # ---- 盈亏曲线
    if len(acc.get("equity_curve", [])) >= 2:
        import plotly.graph_objects as _go
        ec = acc["equity_curve"]
        fig = _go.Figure()
        fig.add_trace(_go.Scatter(x=[p["date"] for p in ec],
                                  y=[p["total"] for p in ec],
                                  name=T("总资产", "Total equity"), line=dict(color="#ef5350", width=2)))
        fig.add_hline(y=acc.get("start_cash", default_cash), line_dash="dash",
                      line_color="#8e9199", annotation_text=T("起始资金", "Starting capital"))
        fig.update_layout(template="plotly_dark", height=300,
                          title=T(f"账户总资产曲线（{cur}）", f"Account equity curve ({cur})"), margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # ---- 成交流水
    if acc.get("trades"):
        with st.expander(T(f"🧾 成交流水（共 {len(acc['trades'])} 笔）", f"🧾 Trade history ({len(acc['trades'])})"), expanded=False):
            import pandas as _pd
            dft = _pd.DataFrame(acc["trades"][::-1])
            dft = dft.rename(columns={"date": T("时间", "Time"), "code": T("代码", "Symbol"),
                                      "name": T("名称", "Name"), "side": T("方向", "Side"),
                                      "shares": T("股数", "Shares"), "price": T("价格", "Price"),
                                      "amount": T("金额", "Amount"), "pnl": T("实现盈亏", "Realized P/L"),
                                      "reason": T("理由", "Reason")})
            if ui_i18n.is_english() and T("理由", "Reason") in dft.columns:
                dft[T("理由", "Reason")] = "Model-generated rebalance instruction"
            st.dataframe(dft, use_container_width=True, height=320)

    # ---- 备份/恢复
    with st.expander(T("💾 备份 / 恢复账户", "💾 Back up / restore account"), expanded=False):
        import json as _json
        st.download_button(T("⬇ 下载账户存档（JSON）", "⬇ Download account archive (JSON)"),
                           data=_json.dumps(acc, ensure_ascii=False, indent=2),
                           file_name=dl_name, mime="application/json",
                           key=f"dl_{acc_key}")
        up = st.file_uploader(T("⬆ 上传账户存档恢复", "⬆ Upload an account archive"), type=["json"], key=f"accup_{acc_key}")
        if up is not None:
            try:
                acc2 = _json.load(up)
                st.session_state[acc_key] = acc2
                paper.save_account(acc2, acc_path)
                st.success(T("账户存档已恢复，请重新运行查看。", "Account archive restored. Rerun to view it."))
            except Exception as _e:
                st.error(T(f"存档解析失败：{_e}", f"Could not parse the archive: {_e}"))

    st.caption(T("⚠️ 纯模拟演示，不连接券商、不下真实订单，未计交易成本与滑点。仅供研究，不构成投资建议。",
                 "⚠️ Paper-trading demonstration only. No broker connection or real orders; costs and slippage are excluded. Not investment advice."))

# ================================================================ TAB 3 选股池
with tab3:
    st.markdown(T("#### 🔭 高科技股票池 — 在持仓之外寻找机会", "#### 🔭 U.S. Technology Screener — find ideas beyond your portfolio"))
    tech_themes = list(universe.TECH_UNIVERSE.keys())
    sel3 = st.multiselect(T("① 选择领域（留空 = 全部科技主题）", "① Choose themes (blank = all)"),
                          tech_themes, default=[], format_func=_theme_label,
                          key="theme_tech", placeholder=T("选择一个或多个主题…", "Choose one or more themes…"))
    cset = st.columns([1, 1, 2])
    top_n = cset[0].slider(T("显示前 N 名", "Show top N"), 5, 30, 15)
    excl_held = cset[1].checkbox(T("排除已持仓", "Exclude holdings"), value=True)
    cset[2].caption(T("可选主题：", "Available themes: ") + " · ".join(_theme_label(x) for x in tech_themes))

    exclude = set(watchlist.keys()) if excl_held else set()
    if st.button(T("🔭 开始扫描科技池（约30–60秒）", "🔭 Scan technology stocks (30–60 sec)"), key="scan_tech", type="primary") \
            or st.session_state.get("scanned_tech"):
        st.session_state["scanned_tech"] = True
        scr = load_screen("科技", tuple(sorted(exclude)), period, use_fund, top_n,
                          tuple(sel3))
        _render_screen(scr)
    else:
        st.info(T("选择领域（可留空），然后点击按钮开始扫描。", "Choose themes (or leave blank), then start the scan."))
    st.caption(T("股票池定义在 universe.py 中。扫描默认不含新闻并缓存 30 分钟。仅供研究，不构成投资建议。",
                 "The universe is defined in universe.py. Scans exclude news by default and are cached for 30 minutes. Research only."))

# ================================================================ TAB 4 美股其他板块
with tab4:
    st.markdown(T("#### 🇺🇸 美股非科技板块 — 价值、防御与周期", "#### 🇺🇸 U.S. Sectors — value, defensive and cyclical ideas"))
    other_themes = list(universe.US_SECTORS.keys())
    sel4 = st.multiselect(T("① 选择板块（留空 = 全部）", "① Choose sectors (blank = all)"), other_themes,
                          default=[], format_func=_theme_label, key="theme_other",
                          placeholder=T("选择一个或多个板块…", "Choose one or more sectors…"))
    c4a, c4b = st.columns([1, 3])
    topn4 = c4a.slider(T("显示前 N 名", "Show top N"), 5, 30, 15, key="topn4")
    c4b.caption(T("可选板块：", "Available sectors: ") + " · ".join(_theme_label(x) for x in other_themes))
    if st.button(T("🇺🇸 开始扫描非科技板块（约30–60秒）", "🇺🇸 Scan U.S. sectors (30–60 sec)"), key="scan_other", type="primary") \
            or st.session_state.get("scanned_other"):
        st.session_state["scanned_other"] = True
        scr4 = load_screen("非科技", (), period, use_fund, topn4, tuple(sel4))
        _render_screen(scr4)
    else:
        st.info(T("选择板块（可留空），然后点击按钮开始扫描。", "Choose sectors (or leave blank), then start the scan."))
    st.caption(T("⚠️ 仅供研究，不构成投资建议。", "⚠️ Research only, not investment advice."))

# ================================================================ TAB 5 A股
with tab5:
    st.markdown(T("#### 🇨🇳 A股龙头选股 — 沪深主要行业龙头", "#### 🇨🇳 China A-share Leaders — major sector leaders"))
    a_themes = list(ashare.A_UNIVERSE.keys())
    sel5 = st.multiselect(T("① 选择行业（留空 = 全部）", "① Choose industries (blank = all)"), a_themes,
                          default=[], format_func=_theme_label, key="theme_a",
                          placeholder=T("选择一个或多个行业…", "Choose one or more industries…"))
    st.caption(T("A股缺少英文新闻因子；分析师评级缺失时按中性处理。价格单位为人民币 ¥。",
                 "English-language news is limited for A-shares; missing analyst ratings are treated as neutral. Prices are in CNY (¥)."))
    c5a, c5b = st.columns([1, 3])
    topn5 = c5a.slider(T("显示前 N 名", "Show top N"), 5, 30, 15, key="topn5")
    a_news = c5b.checkbox(T("中文新闻情绪（akshare，海外服务器可能超时）",
                            "Chinese news sentiment (akshare; overseas servers may time out)"), value=False)
    if st.button(T("🇨🇳 开始扫描A股（约1–2分钟）", "🇨🇳 Scan China A-shares (1–2 min)"), key="scan_a", type="primary") \
            or st.session_state.get("scanned_a"):
        st.session_state["scanned_a"] = True
        scr5 = ashare_screen_cached(period, use_fund, topn5, a_news, tuple(sel5))
        _render_screen(scr5, currency="¥")
    else:
        st.info(T("选择行业（可留空）后开始扫描。海外服务器获取 A股数据，尤其中文新闻，可能较慢；本地运行更稳定。",
                  "Choose industries (or leave blank), then scan. A-share data, especially Chinese news, may be slower from overseas servers."))
    st.caption(T("股票池定义在 ashare.py 中；沪市使用 .SS，深市使用 .SZ。仅供研究。",
                 "The universe is defined in ashare.py; use .SS for Shanghai and .SZ for Shenzhen. Research only."))

# ================================================================ TAB 7 指数基金
with tab7:
    st.markdown(T("#### 💹 指数基金 — 美国与中国指数择时轮动", "#### 💹 ETFs — U.S. and China market timing and rotation"))
    st.caption(T("ETF 不使用基本面、分析师和财报因子，主要依据趋势、动量、技术面与大盘环境。美国 ETF 使用 $，中国 ETF 使用 ¥。",
                 "ETF scores emphasize trend, momentum, technicals and market regime; fundamentals, analysts and earnings are excluded. U.S. ETFs use $, Chinese ETFs use ¥."))
    fmkt = st.radio(T("市场", "Market"), [T("🇺🇸 美国指数", "🇺🇸 U.S. indices"), T("🇨🇳 中国指数", "🇨🇳 China indices")],
                    horizontal=True, key="fund_mkt")
    is_us = fmkt.startswith("🇺🇸")
    pool = funds.US_INDEX if is_us else funds.CN_INDEX
    cur = "$" if is_us else "¥"
    mkey = "US" if is_us else "CN"

    fsel = st.multiselect(T("① 选择领域（留空 = 全部）", "① Choose categories (blank = all)"),
                          list(pool.keys()), default=[], format_func=_theme_label,
                          key=f"theme_fund_{mkey}",
                          placeholder=T("宽基 / 行业 / 债券黄金 / 主题…", "Broad market / sectors / bonds / themes…"))
    fc1, fc2 = st.columns([1, 2])
    topnf = fc1.slider(T("显示前 N 名", "Show top N"), 5, 30, 15, key=f"topnf_{mkey}")
    fq = fc2.text_input(T("② 或直接搜索单只基金（如 QQQ / 沪深300）",
                          "② Or search for one fund (e.g. QQQ / CSI 300)"),
                        key=f"fund_q_{mkey}", placeholder=T("留空则使用上方扫描", "Leave blank to use the screener")).strip()

    # 单只基金详情优先
    if fq:
        cands = search_fund_cached(fq, mkey)
        if not cands:
            st.warning(T("基金池中没有匹配结果；可到“个股详情”直接输入 ETF 代码（如 SPY / 510300.SS）。",
                         "No fund matched. Enter an ETF symbol such as SPY or 510300.SS under Stock details."))
        else:
            i = st.selectbox(T("匹配结果", "Matches"), range(len(cands)),
                             format_func=lambda i: f"{cands[i][0]} · {cands[i][1]}",
                             key=f"fund_pick_{mkey}")
            fcode, fname = cands[i]
            finfo = analyze_single(fcode, fname, period, False, use_fund)
            if not finfo or finfo.get("__error__") or "df" not in finfo:
                st.error(T(f"未能获取 {fcode} 的行情数据。", f"Could not retrieve market data for {fcode}."))
            else:
                render_detail(fcode, finfo, currency=cur, name=fname)
    else:
        if st.button(T("💹 开始扫描指数基金（约30–60秒）", "💹 Scan ETFs (30–60 sec)"), key=f"scan_fund_{mkey}",
                     type="primary") or st.session_state.get(f"scanned_fund_{mkey}"):
            st.session_state[f"scanned_fund_{mkey}"] = True
            scrf = load_fund_screen(mkey, period, use_fund, topnf, tuple(fsel))
            _render_screen(scrf, currency=cur)
        else:
            st.info(T("选择领域（可留空）后扫描，或在②中搜索单只基金。",
                      "Choose categories (or leave blank) and scan, or search for one fund in field ②."))
    st.caption(T("基金池定义在 funds.py 中。仅供研究，不构成投资建议。",
                 "The fund universe is defined in funds.py. Research only, not investment advice."))


# ================================================================ TAB 6 模型原理
with tab6:
    st.markdown(T("## 📖 模型原理", "## 📖 Methodology"))
    st.warning(T("这是一个**多因子打分排序与择时工具**，不是股价预测器。系统对股票当前特征进行排序，并给出基于规则的风险区间；有效性应以回测指标评估。",
                 "This is a **multi-factor ranking and timing tool**, not a price predictor. It ranks current security characteristics and provides rule-based risk levels; evaluate it through backtest metrics."))

    st.markdown(T("### 综合分 = 12 个加权因子（0–100）+ 大盘环境微调",
                  "### Composite score = 12 weighted factors (0–100) + market-regime adjustment"))
    if ui_i18n.is_english():
        _weight_rows = [
            ["Fundamentals", "14%", "PEG, revenue growth, gross margin, ROE and net margin", "yfinance"],
            ["Trend", "13%", "Price vs SMA50/SMA200, crossovers and ADX", "Technicals"],
            ["Analyst expectations", "11%", "Consensus rating, target upside and analyst coverage", "yfinance"],
            ["Momentum", "10%", "MACD, one- and six-month momentum, KDJ", "Technicals"],
            ["Earnings quality", "10%", "Earnings surprises, growth and forward EPS revisions", "yfinance"],
            ["Money flow", "9%", "OBV, CMF, MFI and volume-confirmed breakouts", "Technicals"],
            ["Ownership", "8%", "Institutional/insider ownership and short interest", "yfinance"],
            ["Risk", "8%", "Annualized volatility", "Technicals"],
            ["Relative strength", "7%", "63-day performance relative to QQQ", "Technicals"],
            ["Sector strength", "6%", "A-share industry breadth or U.S. sector-ETF momentum", "Eastmoney / ETFs"],
            ["News sentiment", "6%", "VADER and market-specific financial sentiment lexicons", "News"],
            ["Oscillator strength", "4%", "RSI and Bollinger %B", "Technicals"],
        ]
        _weight_columns = ["Factor", "Weight", "Representative inputs", "Source"]
    else:
        _weight_rows = [
            ["基本面", "14%", "PEG、营收增速、毛利率、ROE、净利率", "yfinance"],
            ["趋势", "13%", "价格相对 SMA50/200、均线交叉、ADX", "技术指标"],
            ["分析师", "11%", "评级均值、目标价上行空间、覆盖分析师数", "yfinance"],
            ["动量", "10%", "MACD、6月/1月涨幅、KDJ", "技术指标"],
            ["盈利质量", "10%", "盈利惊喜、盈利同比增速、预期 EPS 改善", "yfinance"],
            ["资金流", "9%", "OBV、CMF、MFI、放量突破", "技术指标"],
            ["筹码面", "8%", "机构持股、内部人持股、做空比例", "yfinance"],
            ["风险", "8%", "年化波动率", "技术指标"],
            ["相对大盘", "7%", "近63日相对 QQQ 的表现", "技术指标"],
            ["板块热度", "6%", "A股行业宽度或美股板块 ETF 动量", "东财 / ETF"],
            ["新闻情绪", "6%", "VADER 与市场专用财经情绪词典", "新闻"],
            ["强弱", "4%", "RSI、布林 %B", "技术指标"],
        ]
        _weight_columns = ["因子", "权重", "代表性指标", "来源"]
    wdf = pd.DataFrame(_weight_rows, columns=_weight_columns)
    st.table(wdf)
    st.caption(T("权重会根据当前可用因子自动归一化；缺失的板块数据按中性 50 处理。",
                 "Weights are normalized over available factors; missing sector data receive a neutral score of 50."))
    st.markdown(T("**🌐 大盘环境**：根据 QQQ 的 50/200 日均线和近月动量判断 Risk-On / Risk-Off。Risk-On 时适度加分（×1.05），Risk-Off 时适度减分（×0.93）。",
                  "**🌐 Market regime:** uses QQQ's 50/200-day trends and recent momentum. Risk-On modestly raises scores (×1.05); Risk-Off reduces them (×0.93)."))

    st.markdown(T("""
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
""", """
### Score-to-signal mapping
| Score | Signal | Interpretation |
|---|---|---|
| ≥70 | Strong Buy ▲▲ | Broad positive factor agreement |
| 58–69 | Buy ▲ | Moderately positive profile |
| 45–57 | Hold — | Mixed or neutral evidence |
| 35–44 | Reduce ▼ | Deteriorating factor profile |
| <35 | Sell ▼▼ | Broad negative factor agreement |

### Risk rules
- **Stop level** = current price − 2.5 × ATR
- **Target level** = current price + 4 × ATR
- **Suggested weight** = composite score adjusted by volatility, capped at 25% per security
- **Earnings warning** = flag releases within seven days because gap risk is elevated

### What the model actually estimates
The model does not predict a specific daily return. It assumes that when several independent dimensions—valuation, trend, money flow, ownership and news—agree, the security has a stronger medium-term profile. Multi-factor voting reduces reliance on any single noisy indicator.

### How to evaluate it
Open **Stock details** and review annualized return, Sharpe ratio, maximum drawdown and in-position win rate. Historical backtests are more informative than visually judging a few recent signals.

### Portfolio backtest and AI Trader
- **Portfolio backtest:** treats the favorites list as one portfolio and compares score-driven timing with buy-and-hold.
- **AI Trader:** maintains persistent U.S. and China paper accounts, rebalances from current scores, logs trades and tracks an equity curve. It never sends real broker orders.

> Indicators include SMA20/50/200, EMA, MACD, RSI, Bollinger Bands, ATR, ADX/±DI, KDJ, MFI, OBV, CMF and 52-week highs.
"""))


# ================================================================ TAB 我的 / 管理
if tab_me is not None:
    with tab_me:
        st.subheader(T("⚙️ 我的账户与设置", "⚙️ Account & settings"))
        _p = userstore.get_profile(CURRENT_USER) or {}
        st.markdown(T(f"**账户**：{CURRENT_USER}　|　注册：{_p.get('created_at','—')}　|　上次登录：{_p.get('last_login','—')}",
                      f"**Account:** {CURRENT_USER}　|　Created: {_p.get('created_at','—')}　|　Last sign-in: {_p.get('last_login','—')}"))

        st.markdown(T("#### 🔔 推送设置", "#### 🔔 Notification settings"))
        with st.form("me_notify"):
            sk = st.text_input(T("微信推送 SendKey（Server酱）", "WeChat SendKey (ServerChan)"), value=_p.get("sendkey", "") or "",
                               type="password",
                               help=T("在 sct.ftqq.com 获取 SendKey；留空则不推送。",
                                      "Get a SendKey from sct.ftqq.com, or leave blank to disable WeChat notifications."))
            nemail = st.text_input(T("通知邮箱", "Notification email"), value=_p.get("notify_email", "") or CURRENT_USER)
            okn = st.form_submit_button(T("保存推送设置", "Save notification settings"), type="primary")
        if okn:
            if userstore.update_profile(CURRENT_USER, sendkey=sk, notify_email=nemail):
                st.success(T("推送设置已保存。", "Notification settings saved."))
            else:
                st.error(T("保存失败，请重试。", "Could not save settings. Try again."))

        st.markdown(T("#### 🔑 修改密码", "#### 🔑 Change password"))
        with st.form("me_pw"):
            np1 = st.text_input(T("新密码（至少6位）", "New password (6+ characters)"), type="password")
            np2 = st.text_input(T("确认新密码", "Confirm new password"), type="password")
            okp = st.form_submit_button(T("更新密码", "Update password"))
        if okp:
            if np1 != np2:
                st.error(T("两次密码不一致。", "The passwords do not match."))
            else:
                good, msg = userstore.change_password(CURRENT_USER, np1)
                (st.success if good else st.error)(
                    T(msg, "Password updated." if good else "Could not update the password."))

        # 管理员: 所有用户一览
        if auth.is_admin():
            st.divider()
            st.markdown(T("#### 🛡️ 管理员 · 所有用户", "#### 🛡️ Administrator · all users"))
            _users = userstore.list_users()
            st.caption(T(f"后端：{userstore.backend_name()}　|　共 {len(_users)} 位用户",
                         f"Backend: {userstore.backend_name()}　|　{len(_users)} users"))
            if _users:
                import pandas as _pd
                _df = _pd.DataFrame(_users)
                for _col in ("email", "created_at", "last_login", "sendkey",
                             "notify_email", "is_admin", "watchlist_text"):
                    if _col not in _df.columns:
                        _df[_col] = ""
                _push_col = T("有微信推送", "WeChat enabled")
                _df[_push_col] = _df["sendkey"].apply(lambda x: "✅" if str(x).strip() else "—")
                _show = _df[["email", "is_admin", "created_at", "last_login",
                             _push_col, "notify_email"]].rename(
                    columns={"email": T("邮箱", "Email"), "is_admin": T("管理员", "Admin"),
                             "created_at": T("注册时间", "Created"), "last_login": T("上次登录", "Last sign-in"),
                             "notify_email": T("通知邮箱", "Notification email")})
                st.dataframe(_show, use_container_width=True,
                             height=min(80 + 36 * len(_show), 500))
            if userstore.using_supabase():
                st.caption(T("也可在 Supabase 后台 → Table Editor → users 中查看或编辑。",
                             "You can also manage users in Supabase → Table Editor → users."))

        st.caption(T("⚠️ SendKey 与邮箱仅保存在私有后端，不会进入公开仓库，只用于发送通知。",
                     "⚠️ SendKey and email are stored only in the private backend, never in the public repository, and are used only for notifications."))

# ================================================================ TAB 待确认交易 (手机端半自动)
if tab_orders is not None:
    with tab_orders:
        _render_pending_orders()
